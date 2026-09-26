import asyncio
import json
import time
from datetime import datetime, timezone

import httpx
import pytest

from capability_router import usage
from capability_router.usage import (
    UsageError,
    UsageUnavailable,
    collect,
    command_code_monthly_window,
    command_code_plan_credits,
    cursor_auth_path,
    parse_codexbar,
    parse_command_code,
    parse_cursor,
    run_command,
    sanitize_message,
)

NOW = datetime(2026, 9, 23, 7, 48, tzinfo=timezone.utc)
EMAIL = "operator@example.com"
TOKEN = "sk-live-" + "a" * 40
ACCOUNT = "org_7f3c9a1e"

CODEX_STDOUT = "\n".join([
    "codexbar 1.7.0",
    "[info] refreshing oauth credentials",
    json.dumps([{
        "provider": "codex",
        "source": "oauth",
        "usage": {
            "primary": None,
            "secondary": {"usedPercent": 64, "windowMinutes": 10080, "resetsAt": "2026-09-26T03:00:00Z"},
            "tertiary": None,
        },
    }]),
])
CLAUDE_STDOUT = json.dumps([{
    "provider": "claude",
    "usage": {
        "primary": {"usedPercent": 14, "windowMinutes": 300, "resetsAt": "2026-09-23T10:00:00Z"},
        "secondary": {"usedPercent": 23, "windowMinutes": 10080, "resetsAt": "2026-09-29T00:00:00Z"},
        "extraRateWindows": [
            {"id": "opus", "title": "Opus", "window": {"usedPercent": 36, "windowMinutes": 10080, "resetsAt": "2026-09-29T00:00:00Z"}},
            {"id": "sonnet", "title": "Sonnet", "window": {"usedPercent": 2, "windowMinutes": 10080, "resetsAt": "2026-09-29T00:00:00Z"}},
        ],
    },
}])
CURSOR_PAYLOAD = {
    "billingCycleEnd": "1790251555000",
    "planUsage": {"totalSpend": 800, "remaining": 1200, "limit": 2000, "totalPercentUsed": 41},
}
PLAN = {"planId": "individual-goat", "status": "active", "currentPeriodEnd": "2026-10-21T02:28:00.000Z"}
CC_CREDITS = {
    "windowLimits": {
        "fiveHour": {"used": 0.149872142, "cap": 14, "resetAt": 1790163159842},
        "weekly": {"used": 1.549419221, "cap": 35, "resetAt": 1790569800776},
    },
    "credits": {"monthlyCredits": 68.19, "purchasedCredits": 0, "freeCredits": 0},
}


def iso_ms(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# --- codexbar ---------------------------------------------------------------------------------


def test_codexbar_codex_keeps_the_weekly_only_window_and_skips_log_lines():
    assert parse_codexbar(CODEX_STDOUT) == {
        "windows": [{"label": "週", "remainingPercent": 36, "resetsAt": "2026-09-26T03:00:00.000Z", "period": "week"}],
    }


def test_codexbar_claude_keeps_the_extra_rate_windows():
    assert parse_codexbar(CLAUDE_STDOUT)["windows"] == [
        {"label": "5h", "remainingPercent": 86, "resetsAt": "2026-09-23T10:00:00.000Z", "period": "5h"},
        {"label": "週", "remainingPercent": 77, "resetsAt": "2026-09-29T00:00:00.000Z", "period": "week"},
        # a limit on some models only: marked scoped, and routing ignores it
        {"label": "Opus", "remainingPercent": 64, "resetsAt": "2026-09-29T00:00:00.000Z", "period": "week", "scoped": True},
        {"label": "Sonnet", "remainingPercent": 98, "resetsAt": "2026-09-29T00:00:00.000Z", "period": "week", "scoped": True},
    ]


def test_codexbar_surfaces_its_error_and_rejects_junk():
    with pytest.raises(UsageError, match="not logged in"):
        parse_codexbar(json.dumps([{"provider": "claude", "error": {"code": "auth", "message": "not logged in"}}]))
    with pytest.raises(UsageError, match="JSONを取り出せませんでした"):
        parse_codexbar("codexbar: no json here\n[info] still [not json")
    with pytest.raises(UsageError, match="usage JSONが空です"):
        parse_codexbar("[]")
    with pytest.raises(UsageError, match="usage windowがありません"):
        parse_codexbar(json.dumps([{"provider": "codex", "usage": {"primary": None}}]))


def test_codexbar_is_called_with_the_oauth_source_and_the_configured_command():
    calls = []

    async def run(command, args, timeout):
        calls.append((command, args))
        return CODEX_STDOUT

    env = {"CAPABILITY_ROUTER_CODEXBAR": "/opt/fake/codexbar"}
    snap = asyncio.run(collect(env, run=run, transport=httpx.MockTransport(lambda r: httpx.Response(500)), now=lambda: NOW))
    assert sorted(calls) == [
        ("/opt/fake/codexbar", ["usage", "--provider", "claude", "--source", "oauth", "--json-only"]),
        ("/opt/fake/codexbar", ["usage", "--provider", "codex", "--source", "oauth", "--json-only"]),
    ]
    assert [s["status"] for s in snap["services"][:2]] == ["ok", "ok"]


def test_codexbar_defaults_to_the_command_on_path():
    calls = []

    async def run(command, args, timeout):
        calls.append(command)
        return CODEX_STDOUT

    asyncio.run(collect({}, run=run, transport=httpx.MockTransport(lambda r: httpx.Response(500))))
    assert calls == ["codexbar", "codexbar"]


# --- run_command --------------------------------------------------------------------------------


def _script(tmp_path, name, body):
    path = tmp_path / name
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o755)
    return str(path)


def test_run_command_discards_stderr_and_reports_failures(tmp_path):
    ok = _script(tmp_path, "ok", f"echo 'secret {EMAIL}' >&2\necho out\n")
    assert asyncio.run(run_command(ok, [], 5)) == "out\n"
    failing = _script(tmp_path, "fail", f"echo '{TOKEN}' >&2\nexit 3\n")
    with pytest.raises(UsageError, match="^コマンドが失敗しました$"):
        asyncio.run(run_command(failing, [], 5))
    with pytest.raises(UsageUnavailable, match="コマンドが見つかりません"):
        asyncio.run(run_command(str(tmp_path / "missing"), [], 5))
    slow = _script(tmp_path, "slow", "exec sleep 30\n")
    with pytest.raises(UsageError, match="応答がありません"):
        asyncio.run(run_command(slow, [], 0.2))


# --- Cursor -------------------------------------------------------------------------------------


def test_cursor_converts_cents_to_the_remaining_percent_of_the_month():
    assert parse_cursor(CURSOR_PAYLOAD) == {
        "windows": [{
            "label": "月",
            "remainingPercent": 60,
            "resetsAt": iso_ms(1790251555000),
            "period": "month",
            "detail": "$12.00 / $20.00",
        }],
    }
    with pytest.raises(UsageError, match="不正"):
        parse_cursor({"planUsage": {"remaining": 10}})
    with pytest.raises(UsageError, match="不正"):
        parse_cursor({"planUsage": {"remaining": 10, "limit": 0}})


def test_cursor_auth_path_follows_the_env_and_xdg():
    assert str(cursor_auth_path({"CAPABILITY_ROUTER_CURSOR_AUTH": "/x/auth.json"})) == "/x/auth.json"
    assert str(cursor_auth_path({"XDG_CONFIG_HOME": "/cfg", "HOME": "/h"})) == "/cfg/cursor/auth.json"
    assert str(cursor_auth_path({"HOME": "/h"})) == "/h/.config/cursor/auth.json"


def _cursor_service(tmp_path, handler, auth=None):
    env = {"CAPABILITY_ROUTER_CURSOR_AUTH": str(tmp_path / "auth.json")}
    if auth is not None:
        (tmp_path / "auth.json").write_text(auth, encoding="utf-8")

    async def run(command, args, timeout):
        raise UsageUnavailable("コマンドが見つかりません")

    snap = asyncio.run(collect(env, run=run, transport=httpx.MockTransport(handler), now=lambda: NOW))
    return next(s for s in snap["services"] if s["id"] == "cursor")


def test_cursor_sends_the_access_token_and_never_the_refresh_token(tmp_path):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=CURSOR_PAYLOAD)

    auth = json.dumps({"accessToken": "cursor-token", "refreshToken": "refresh-token"})
    svc = _cursor_service(tmp_path, handler, auth)
    assert svc["status"] == "ok" and svc["windows"][0]["remainingPercent"] == 60
    (req,) = seen
    assert req.method == "POST" and str(req.url) == usage.CURSOR_USAGE_URL
    assert req.headers["Authorization"] == "Bearer cursor-token"
    assert req.content == b"{}"
    assert b"refresh-token" not in req.content and "refresh-token" not in str(req.headers)


def test_cursor_unavailable_without_auth_file_or_token(tmp_path):
    svc = _cursor_service(tmp_path, lambda r: httpx.Response(200, json=CURSOR_PAYLOAD))
    assert (svc["status"], svc["message"]) == ("unavailable", "Cursor の認証ファイルが見つかりません")
    svc = _cursor_service(tmp_path, lambda r: httpx.Response(200, json=CURSOR_PAYLOAD), "{}")
    assert svc["status"] == "unavailable"
    svc = _cursor_service(tmp_path, lambda r: httpx.Response(200, json=CURSOR_PAYLOAD), "not json")
    assert svc["status"] == "error"


@pytest.mark.parametrize("status", [401, 403])
def test_cursor_rejected_token_is_an_expired_login(tmp_path, status):
    svc = _cursor_service(tmp_path, lambda r: httpx.Response(status, text=f"denied {EMAIL}"), '{"accessToken": "t"}')
    assert (svc["status"], svc["message"]) == ("error", "認証切れ（cursor-agent loginが必要）")


def test_cursor_http_error_timeout_and_bad_json(tmp_path):
    auth = '{"accessToken": "t"}'
    svc = _cursor_service(tmp_path, lambda r: httpx.Response(500), auth)
    assert svc["message"] == "Cursor API: HTTP 500"

    def slow(request):
        raise httpx.ReadTimeout("timed out", request=request)

    svc = _cursor_service(tmp_path, slow, auth)
    assert (svc["status"], svc["message"]) == ("error", "応答がありません")
    svc = _cursor_service(tmp_path, lambda r: httpx.Response(200, text="<html>"), auth)
    assert svc["message"] == "usage responseが不正です"


# --- Command Code -----------------------------------------------------------------------------


def test_command_code_plan_table_matches_by_longest_prefix():
    ids = ["individual-go", "individual-goat", "INDIVIDUAL_GOAT_2025", "individual-pro", "individual-pro-v1",
           "individual-provider", "teams_pro_annual", "enterprise", None]
    assert [command_code_plan_credits(i) for i in ids] == [10, 70, 70, 30, 80, 15, 40, None, None]


def test_command_code_monthly_window_follows_the_cli_view():
    credits = {"monthlyCredits": 68.19, "purchasedCredits": 0, "freeCredits": 0}
    w = command_code_monthly_window(credits, PLAN)
    assert (w["label"], w["cap"], round(w["used"], 2)) == ("monthly", 70, 1.81)
    assert w["resetAt"] == datetime(2026, 10, 21, 2, 28, tzinfo=timezone.utc).timestamp() * 1000
    topped = command_code_monthly_window({"monthlyCredits": 90, "purchasedCredits": 5, "freeCredits": 5}, PLAN)
    assert (topped["used"], topped["cap"]) == (0, 100)
    assert command_code_monthly_window({"monthlyCredits": 20, "purchasedCredits": 10, "freeCredits": 0}, PLAN)["used"] == 50
    assert command_code_monthly_window(credits, {**PLAN, "status": "canceled"}) is None
    assert command_code_monthly_window(credits, {**PLAN, "planId": "enterprise"}) is None
    assert command_code_monthly_window({}, PLAN) is None
    assert command_code_monthly_window(credits, {**PLAN, "currentPeriodEnd": None})["resetAt"] is None


def test_command_code_normalizes_5h_week_and_month():
    result = parse_command_code(CC_CREDITS, {"data": PLAN})
    assert result == {
        "plan": "individual-goat",
        "windows": [
            {"label": "5h", "remainingPercent": 99, "resetsAt": iso_ms(1790163159842), "period": "5h", "detail": "$13.85 / $14.00"},
            {"label": "週", "remainingPercent": 96, "resetsAt": iso_ms(1790569800776), "period": "week", "detail": "$33.45 / $35.00"},
            {"label": "月", "remainingPercent": 97, "resetsAt": "2026-10-21T02:28:00.000Z", "period": "month", "detail": "$68.19 / $70.00"},
        ],
    }


@pytest.mark.parametrize("plan", [{**PLAN, "status": "canceled"}, {**PLAN, "planId": "enterprise-x"}])
def test_command_code_credits_stand_alone_without_a_monthly_window(plan):
    result = parse_command_code(CC_CREDITS, {"data": plan})
    assert [w["label"] for w in result["windows"]] == ["5h", "週"]
    assert result["credits"] == {"label": "月クレジット", "remaining": 68.19, "unit": "USD"}


def test_command_code_without_windows_is_an_error():
    with pytest.raises(UsageError, match="usage windowがありません"):
        parse_command_code({}, {})


def _command_code_service(env, handler):
    async def run(command, args, timeout):
        raise UsageUnavailable("コマンドが見つかりません")

    snap = asyncio.run(collect(env, run=run, transport=httpx.MockTransport(handler), now=lambda: NOW))
    return next(s for s in snap["services"] if s["id"] == "commandcode")


def _command_code_api(seen=None):
    def handler(request):
        if seen is not None:
            seen.append(request)
        path = request.url.path
        if path == "/alpha/whoami":
            return httpx.Response(200, json={"email": EMAIL, "org": {"id": ACCOUNT}})
        if path == "/alpha/billing/credits":
            return httpx.Response(200, json=CC_CREDITS)
        if path == "/alpha/billing/subscriptions":
            return httpx.Response(200, json={"data": PLAN})
        return httpx.Response(404)

    return handler


def test_command_code_fetches_with_the_api_key_and_org():
    seen = []
    svc = _command_code_service({"COMMAND_CODE_API_KEY": "cc-key"}, _command_code_api(seen))
    assert svc["status"] == "ok" and [w["label"] for w in svc["windows"]] == ["5h", "週", "月"]
    assert [r.url.path for r in seen][0] == "/alpha/whoami"
    assert seen[0].url.params["limits"] == "1"
    assert all(r.headers["Authorization"] == "Bearer cc-key" for r in seen)
    assert all(r.url.params.get("orgId") == ACCOUNT for r in seen[1:])


def test_command_code_is_unavailable_without_a_key_and_expired_on_401():
    svc = _command_code_service({}, _command_code_api())
    assert (svc["status"], svc["message"]) == ("unavailable", "COMMAND_CODE_API_KEY がありません")
    svc = _command_code_service({"COMMAND_CODE_API_KEY": "k"}, lambda r: httpx.Response(401))
    assert (svc["status"], svc["message"]) == ("error", "認証切れ（COMMAND_CODE_API_KEY を確認）")


# --- the whole snapshot -------------------------------------------------------------------------


def test_one_hanging_service_times_out_without_holding_back_the_others(tmp_path):
    async def run(command, args, timeout):
        if "codex" in args:
            await asyncio.sleep(30)
        return CLAUDE_STDOUT

    env = {"CAPABILITY_ROUTER_CURSOR_AUTH": str(tmp_path / "none.json")}
    started = time.monotonic()
    snap = asyncio.run(
        collect(env, run=run, transport=httpx.MockTransport(lambda r: httpx.Response(500)), timeout=0.2, now=lambda: NOW)
    )
    assert time.monotonic() - started < 5
    assert [(s["id"], s["status"]) for s in snap["services"]] == [
        ("codex", "error"), ("claude", "ok"), ("cursor", "unavailable"), ("commandcode", "unavailable"),
    ]
    assert snap["services"][0]["message"] == "応答がありません"
    assert snap["services"][0]["windows"] == []


def test_a_failing_service_never_stops_the_others(tmp_path):
    async def run(command, args, timeout):
        if "claude" in args:
            raise RuntimeError("boom")
        return CODEX_STDOUT

    auth = tmp_path / "auth.json"
    auth.write_text('{"accessToken": "t"}', encoding="utf-8")
    snap = asyncio.run(collect(
        {"CAPABILITY_ROUTER_CURSOR_AUTH": str(auth)},
        run=run,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=CURSOR_PAYLOAD)),
        now=lambda: NOW,
    ))
    assert snap["fetchedAt"] == "2026-09-23T07:48:00.000Z"
    assert [s["status"] for s in snap["services"]] == ["ok", "error", "ok", "unavailable"]
    assert snap["services"][1]["message"] == "boom"


def test_sanitize_message_redacts_secrets_and_paths():
    cleaned = sanitize_message(f"auth failed for {EMAIL} token={TOKEN} at /home/operator/.config/cursor/auth.json")
    assert EMAIL not in cleaned and TOKEN not in cleaned and "/home/operator" not in cleaned
    assert "[redacted]" in cleaned and "[internal path]" in cleaned
    assert "abc.def" not in sanitize_message("request failed: Bearer abc.def")
    assert len(sanitize_message("x" * 20 + " " + "y " * 200)) <= 160
    assert sanitize_message("") == "取得に失敗しました"
    assert sanitize_message(None) == "取得に失敗しました"


def test_snapshot_never_carries_tokens_emails_account_ids_or_stderr(tmp_path):
    # codexbar leaks an email and a token on stderr and in its error message; Cursor echoes the
    # token in a rejected response; Command Code's whoami carries the email and the org id.
    codexbar = _script(
        tmp_path,
        "codexbar",
        f"echo 'stderr {EMAIL} {TOKEN}' >&2\n"
        f"echo '[{{\"provider\": \"x\", \"error\": {{\"message\": \"not logged in as {EMAIL} token={TOKEN}\"}}}}]'\n",
    )
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"accessToken": TOKEN, "refreshToken": "r" * 50}), encoding="utf-8")

    def handler(request):
        if request.url.host == "api2.cursor.sh":
            return httpx.Response(401, text=f"bad token {TOKEN} for {EMAIL}")
        return _command_code_api()(request)

    env = {"CAPABILITY_ROUTER_CODEXBAR": codexbar, "CAPABILITY_ROUTER_CURSOR_AUTH": str(auth), "COMMAND_CODE_API_KEY": TOKEN}
    snap = asyncio.run(collect(env, transport=httpx.MockTransport(handler), now=lambda: NOW))
    text = json.dumps(snap, ensure_ascii=False)
    for secret in (TOKEN, EMAIL, ACCOUNT, "stderr", "r" * 50, str(tmp_path)):
        assert secret not in text
    assert [s["status"] for s in snap["services"]] == ["error", "error", "error", "ok"]
    assert snap["services"][0]["message"].startswith("not logged in as [redacted]")


# --- the CLI ------------------------------------------------------------------------------------


@pytest.fixture
def fake_services(tmp_path, monkeypatch):
    """A fake codexbar on disk, a Cursor auth file, and a mocked Cursor / Command Code API."""
    codexbar = _script(
        tmp_path,
        "codexbar",
        f"echo 'stderr {EMAIL}' >&2\n"
        f"if [ \"$3\" = codex ]; then cat <<'JSON'\n{CODEX_STDOUT}\nJSON\nelse cat <<'JSON'\n{CLAUDE_STDOUT}\nJSON\nfi\n",
    )
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"accessToken": "cursor-token"}), encoding="utf-8")
    monkeypatch.setenv("CAPABILITY_ROUTER_CODEXBAR", codexbar)
    monkeypatch.setenv("CAPABILITY_ROUTER_CURSOR_AUTH", str(auth))
    monkeypatch.setenv("COMMAND_CODE_API_KEY", "cc-key")

    def handler(request):
        if request.url.host == "api2.cursor.sh":
            return httpx.Response(200, json=CURSOR_PAYLOAD)
        return _command_code_api()(request)

    real = usage.snapshot
    monkeypatch.setattr(usage, "snapshot", lambda: real(transport=httpx.MockTransport(handler)))


def test_cli_usage_json_has_the_day_plan_shape(fake_services, capsys):
    from capability_router.cli import main

    assert main(["usage", "--json"]) == 0
    out = capsys.readouterr().out
    snap = json.loads(out)
    assert set(snap) == {"fetchedAt", "services"}
    assert [(s["id"], s["name"], s["status"]) for s in snap["services"]] == [
        ("codex", "Codex", "ok"),
        ("claude", "Claude Code", "ok"),
        ("cursor", "Cursor Pro", "ok"),
        ("commandcode", "Command Code", "ok"),
    ]
    for s in snap["services"]:
        assert set(s) <= {"id", "name", "plan", "status", "message", "fetchedAt", "windows", "credits"}
        assert s["fetchedAt"] == snap["fetchedAt"]
        for w in s["windows"]:
            assert set(w) <= {"label", "remainingPercent", "resetsAt", "period", "scoped", "detail"}
            assert isinstance(w["remainingPercent"], int) and 0 <= w["remainingPercent"] <= 100
    assert [w["label"] for w in snap["services"][1]["windows"]] == ["5h", "週", "Opus", "Sonnet"]
    assert snap["services"][3]["plan"] == "individual-goat"
    assert EMAIL not in out and "cursor-token" not in out and "cc-key" not in out and ACCOUNT not in out


def test_cli_usage_table_and_exit_code_with_failing_services(fake_services, monkeypatch, tmp_path, capsys):
    from capability_router.cli import main

    monkeypatch.setenv("CAPABILITY_ROUTER_CODEXBAR", str(tmp_path / "missing"))
    monkeypatch.delenv("COMMAND_CODE_API_KEY")
    assert main(["usage"]) == 0
    out = capsys.readouterr().out
    assert "Codex" in out and "unavailable" in out and "コマンドが見つかりません" in out
    assert "Cursor Pro" in out and "60%" in out and "$12.00 / $20.00" in out


def test_cli_usage_keeps_a_readable_detail_column(fake_services, capsys, monkeypatch):
    # The detail column wraps, but never to one or two characters: it gets a readable minimum and
    # the table is allowed to grow past the terminal width instead.
    from capability_router.cli import main

    monkeypatch.setattr("capability_router.cli._is_terminal", lambda: True)
    monkeypatch.setenv("COLUMNS", "80")
    assert main(["usage"]) == 0
    out = capsys.readouterr().out
    header = next(ln for ln in out.splitlines() if ln.startswith("service"))
    assert len(header) - header.index("detail") >= 12
    assert any("Command Code (individual-goat)" in line for line in out.splitlines())
