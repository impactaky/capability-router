"""Remaining usage of the AI services the router's configs are run through.

`capability-router usage` fetches every service concurrently and bounds each one separately, so
one slow or failing service never holds back the others. This module is the only place that names
the services: `SERVICE_IDS` is what `pool.yaml` and the services settings may refer to, and
routing reads a snapshot's numbers without knowing where they came from. `route` reads the
snapshot through a 5-minute cache (`cached_snapshot`); `usage` always fetches and refreshes it.

The normalized snapshot never carries tokens, emails, account identifiers, or command stderr:
stderr is discarded, credentials only go into request headers, and every failure message passes
through `sanitize_message` before it reaches the output.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping
from urllib.parse import quote

import httpx

TIMEOUT_S = 30.0
CACHE_MAX_AGE_S = 300.0

# The services a config can run on, in output order. `pool.yaml` and the services settings refer
# to these ids.
SERVICE_IDS = ("codex", "claude", "cursor", "commandcode")

CURSOR_USAGE_URL = "https://api2.cursor.sh/aiserver.v1.DashboardService/GetCurrentPeriodUsage"
COMMAND_CODE_BASE_URL = "https://api.commandcode.ai"

# Monthly credit grant per plan, transcribed from the Command Code CLI (command-code 1.64.0
# `dist/cli.mjs`, `getPlanTotalCredits` / `getPlanInfo`). The API does not return the grant, so
# update this table when the CLI changes it.
COMMAND_CODE_PLAN_CREDITS = {
    "individual-go": 10,
    "individual-goat": 70,
    "individual-pro": 30,
    "individual-pro-v1": 80,
    "individual-provider": 15,
    "individual-max": 150,
    "individual-ultra": 300,
    "teams-pro": 40,
}

_COMMAND_CODE_LABELS = {"weekly": "週", "monthly": "月"}
_COMMAND_CODE_PERIODS = {"5h": "5h", "weekly": "week", "monthly": "month"}

CommandRunner = Callable[[str, list[str], float], Awaitable[str]]


class UsageUnavailable(Exception):
    """The service's prerequisite is absent (no command, no auth file, no API key)."""


class UsageError(Exception):
    """Fetching was attempted and failed. The message is shown after `sanitize_message`."""


# --- small helpers ---------------------------------------------------------------------------


def _record(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _clamp_percent(value: float) -> int:
    if not math.isfinite(value):
        return 0
    # Round half up (Python's round() is half-to-even).
    return max(0, min(100, math.floor(value + 0.5)))


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _iso_from_epoch_ms(value: Any) -> str | None:
    if isinstance(value, str):
        try:
            ms = float(value)
        except ValueError:
            return None
    else:
        ms = _number(value)
    if ms is None or not math.isfinite(ms) or ms <= 0:
        return None
    try:
        return _iso(datetime.fromtimestamp(ms / 1000, tz=timezone.utc))
    except (OverflowError, OSError, ValueError):
        return None


def _iso_from_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return _iso(dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))


def _json_line(stdout: str, opening: str) -> Any:
    """The first line that starts with `opening` and parses as JSON (commands mix in log lines)."""
    for line in stdout.splitlines():
        text = line.strip()
        if not text.startswith(opening):
            continue
        try:
            return json.loads(text)
        except ValueError:
            continue  # a log line such as "[info] ..." that only looks like JSON
    raise UsageError("usage JSONを取り出せませんでした")


def _usd(value: float) -> str:
    return f"${value:.2f}"


def sanitize_message(value: Any) -> str:
    """Last line of defence before a message reaches the output."""
    text = value if isinstance(value, str) else ""
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", text)
    text = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[redacted]", text)
    text = re.sub(r"\b(?:sk|pk|rk|ghp|github_pat)[_-][A-Za-z0-9_-]{8,}\b", "[redacted]", text, flags=re.I)
    text = re.sub(r"Bearer\s+\S+", "Bearer [redacted]", text, flags=re.I)
    text = re.sub(
        r"((?:token|api[_-]?key|secret|password|authorization)\s*[=:]\s*)\S+",
        r"\1[redacted]",
        text,
        flags=re.I,
    )
    text = re.sub(r"[A-Za-z0-9_-]{40,}", "[redacted]", text)
    text = re.sub(r"(?:^|\s)(?:/[\w.-]+){2,}", " [internal path]", text, flags=re.ASCII)
    text = re.sub(r"\s+", " ", text).strip()[:160]
    return text or "取得に失敗しました"


# --- normalization ---------------------------------------------------------------------------


_PERIODS = {300: "5h", 10080: "week"}


def _codexbar_window(record: dict, title: Any = None, scoped: bool = False) -> dict | None:
    used = _number(record.get("usedPercent"))
    if used is None:
        return None
    minutes = _number(record.get("windowMinutes"))
    period = _PERIODS.get(minutes) if minutes is not None else None
    title = title.strip()[:24] if isinstance(title, str) else ""
    if title:
        label = title
    elif period == "5h":
        label = "5h"
    elif period == "week":
        label = "週"
    elif minutes is not None:
        label = f"{math.floor(minutes + 0.5)}分"
    else:
        label = "枠"
    window = {
        "label": label,
        "remainingPercent": _clamp_percent(100 - used),
        "resetsAt": _iso_from_string(record.get("resetsAt")),
    }
    if period:
        window["period"] = period
    if scoped:
        # a limit on some models of the service only (e.g. one model family's weekly cap)
        window["scoped"] = True
    return window


def parse_codexbar(stdout: str) -> dict:
    parsed = _json_line(stdout, "[")
    if not isinstance(parsed, list) or not parsed:
        raise UsageError("usage JSONが空です")
    entry = _record(parsed[0])
    if entry.get("error"):
        message = _record(entry["error"]).get("message")
        raise UsageError(message if isinstance(message, str) else "codexbar が取得に失敗しました")
    usage = _record(entry.get("usage"))
    windows = []
    for key in ("primary", "secondary", "tertiary"):
        if usage.get(key):
            w = _codexbar_window(_record(usage[key]))
            if w:
                windows.append(w)
    extra = usage.get("extraRateWindows")
    for item in extra if isinstance(extra, list) else []:
        item = _record(item)
        w = _codexbar_window(_record(item.get("window")), item.get("title"), scoped=True)
        if w:
            windows.append(w)
    if not windows:
        raise UsageError("usage windowがありません")
    return {"windows": windows}


def parse_cursor(payload: Any) -> dict:
    payload = _record(payload)
    plan_usage = _record(payload.get("planUsage"))
    remaining = _number(plan_usage.get("remaining"))
    limit = _number(plan_usage.get("limit"))
    if remaining is None or limit is None or limit <= 0:
        raise UsageError("usage responseが不正です")
    # Amounts are in cents. totalPercentUsed has an unknown unit and is intentionally ignored.
    return {
        "windows": [{
            "label": "月",
            "remainingPercent": _clamp_percent(remaining / limit * 100),
            "resetsAt": _iso_from_epoch_ms(payload.get("billingCycleEnd")),
            "period": "month",
            "detail": f"{_usd(remaining / 100)} / {_usd(limit / 100)}",
        }],
    }


def command_code_plan_credits(plan_id: Any) -> float | None:
    """Like the CLI: lower-case, "_" -> "-", and prefix-match the longest key first."""
    if not isinstance(plan_id, str):
        return None
    normalized = plan_id.strip().lower().replace("_", "-")
    for key in sorted(COMMAND_CODE_PLAN_CREDITS, key=len, reverse=True):
        if normalized.startswith(key):
            return COMMAND_CODE_PLAN_CREDITS[key]
    return None


def command_code_monthly_window(credits: dict, plan: dict) -> dict | None:
    """The CLI /usage view (`projectUsageView`) for an active subscription.

    total = max(plan grant, monthlyCredits) + purchased + free; remaining = monthly + purchased +
    free. None when the plan is unknown or not active, or monthlyCredits is missing.
    """
    grant = command_code_plan_credits(plan.get("planId"))
    monthly = _number(credits.get("monthlyCredits"))
    if plan.get("status") != "active" or grant is None or monthly is None:
        return None
    extra = (_number(credits.get("purchasedCredits")) or 0.0) + (_number(credits.get("freeCredits")) or 0.0)
    total = max(grant, monthly) + extra
    period_end = _iso_from_string(plan.get("currentPeriodEnd"))
    reset_ms = datetime.fromisoformat(period_end).timestamp() * 1000 if period_end else None
    return {"label": "monthly", "used": total - (monthly + extra), "cap": total, "resetAt": reset_ms}


def parse_command_code(credits_body: Any, subscription_body: Any) -> dict:
    credits_body = _record(credits_body)
    limits = _record(credits_body.get("windowLimits"))
    credits = _record(credits_body.get("credits"))
    plan = _record(_record(subscription_body).get("data"))
    raw = []
    for key, label in (("fiveHour", "5h"), ("weekly", "weekly")):
        w = _record(limits.get(key))
        raw.append({"label": label, "used": w.get("used"), "cap": w.get("cap"), "resetAt": w.get("resetAt")})
    raw.append(command_code_monthly_window(credits, plan))

    windows = []
    has_monthly = False
    for item in raw:
        item = _record(item)
        used, cap = _number(item.get("used")), _number(item.get("cap"))
        if used is None or cap is None or cap <= 0:
            continue
        label = item["label"]
        has_monthly = has_monthly or label == "monthly"
        windows.append({
            "label": _COMMAND_CODE_LABELS.get(label, label),
            "remainingPercent": _clamp_percent((1 - used / cap) * 100),
            "resetsAt": _iso_from_epoch_ms(item.get("resetAt")),
            "period": _COMMAND_CODE_PERIODS[label],
            "detail": f"{_usd(max(0.0, cap - used))} / {_usd(cap)}",
        })
    if not windows:
        raise UsageError("usage windowがありません")
    result: dict = {"windows": windows}
    plan_id = plan.get("planId")
    if isinstance(plan_id, str) and plan_id.strip():
        result["plan"] = plan_id.strip()[:64]
    # The monthly window already shows the credits as a percentage, so the balance is only a
    # fallback for plans whose grant is unknown or that are not active.
    monthly = _number(credits.get("monthlyCredits"))
    if not has_monthly and monthly is not None:
        result["credits"] = {"label": "月クレジット", "remaining": round(monthly, 2), "unit": "USD"}
    return result


# --- fetching --------------------------------------------------------------------------------


async def run_command(command: str, args: list[str], timeout: float) -> str:
    """stdout of the command. stderr is discarded: it may carry account details."""
    try:
        proc = await asyncio.create_subprocess_exec(
            command,
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except FileNotFoundError:
        raise UsageUnavailable("コマンドが見つかりません") from None
    except OSError:
        raise UsageError("コマンドを実行できません") from None
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        raise UsageError("応答がありません") from None
    finally:
        if proc.returncode is None:  # timed out or cancelled
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()
    if proc.returncode != 0:
        raise UsageError("コマンドが失敗しました")
    return stdout.decode("utf-8", errors="replace")


async def _codexbar(provider: str, env: Mapping[str, str], run: CommandRunner, timeout: float) -> dict:
    command = env.get("CAPABILITY_ROUTER_CODEXBAR") or "codexbar"
    # --source oauth: the default (auto) starts the Claude CLI and takes about 15 seconds.
    stdout = await run(command, ["usage", "--provider", provider, "--source", "oauth", "--json-only"], timeout)
    return parse_codexbar(stdout)


def cursor_auth_path(env: Mapping[str, str]) -> Path:
    if env.get("CAPABILITY_ROUTER_CURSOR_AUTH"):
        return Path(env["CAPABILITY_ROUTER_CURSOR_AUTH"])
    config = env.get("XDG_CONFIG_HOME") or str(Path(env.get("HOME") or Path.home()) / ".config")
    return Path(config) / "cursor" / "auth.json"


async def _cursor(env: Mapping[str, str], client: httpx.AsyncClient) -> dict:
    try:
        contents = cursor_auth_path(env).read_text(encoding="utf-8")
    except OSError:
        raise UsageUnavailable("Cursor の認証ファイルが見つかりません") from None
    try:
        token = _record(json.loads(contents)).get("accessToken")
    except ValueError:
        raise UsageError("Cursor の認証ファイルを読めません") from None
    if not isinstance(token, str) or not token:
        raise UsageUnavailable("Cursor の認証情報がありません")
    try:
        # The refresh token is never used, so cursor-agent's own session stays intact.
        response = await client.post(
            CURSOR_USAGE_URL,
            content=b"{}",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        )
    except httpx.TimeoutException:
        raise UsageError("応答がありません") from None
    except httpx.HTTPError:
        raise UsageError("Cursor APIへ接続できません") from None
    if response.status_code in (401, 403):
        raise UsageError("認証切れ（cursor-agent loginが必要）")
    if not response.is_success:
        raise UsageError(f"Cursor API: HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError:
        raise UsageError("usage responseが不正です") from None
    return parse_cursor(payload)


async def _command_code_get(client: httpx.AsyncClient, path: str, api_key: str) -> Any:
    try:
        response = await client.get(
            COMMAND_CODE_BASE_URL + path,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        )
    except httpx.TimeoutException:
        raise UsageError("応答がありません") from None
    except httpx.HTTPError:
        raise UsageError("Command Code APIへ接続できません") from None
    if response.status_code in (401, 403):
        raise UsageError("認証切れ（COMMAND_CODE_API_KEY を確認）")
    if not response.is_success:
        raise UsageError(f"Command Code API: HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError:
        raise UsageError("usage responseが不正です") from None


async def _command_code(env: Mapping[str, str], client: httpx.AsyncClient) -> dict:
    # The /alpha endpoints are the ones the Command Code CLI's /usage view calls.
    api_key = env.get("COMMAND_CODE_API_KEY")
    if not api_key:
        raise UsageUnavailable("COMMAND_CODE_API_KEY がありません")
    whoami = await _command_code_get(client, "/alpha/whoami?limits=1", api_key)
    org_id = _record(_record(whoami).get("org")).get("id")
    query = f"?orgId={quote(org_id, safe='')}" if isinstance(org_id, str) else ""
    credits, subscription = await asyncio.gather(
        _command_code_get(client, f"/alpha/billing/credits{query}", api_key),
        _command_code_get(client, f"/alpha/billing/subscriptions{query}", api_key),
    )
    return parse_command_code(credits, subscription)


async def _service(sid: str, name: str, fetch: Awaitable[dict], fetched_at: str, timeout: float) -> dict:
    try:
        # Each fetch also bounds its own command or request; this covers a hang anywhere else.
        result = await asyncio.wait_for(fetch, timeout)
    except UsageUnavailable as e:
        return _failed(sid, name, "unavailable", str(e), fetched_at)
    except asyncio.TimeoutError:
        return _failed(sid, name, "error", "応答がありません", fetched_at)
    except Exception as e:  # noqa: BLE001 - one service's failure must not stop the others
        return _failed(sid, name, "error", str(e), fetched_at)
    out: dict = {"id": sid, "name": name}
    if result.get("plan"):
        out["plan"] = result["plan"]
    out.update(status="ok", fetchedAt=fetched_at, windows=result["windows"])
    if result.get("credits"):
        out["credits"] = result["credits"]
    return out


def _failed(sid: str, name: str, status: str, message: str, fetched_at: str) -> dict:
    return {
        "id": sid,
        "name": name,
        "status": status,
        "message": sanitize_message(message),
        "fetchedAt": fetched_at,
        "windows": [],
    }


async def collect(
    env: Mapping[str, str],
    *,
    run: CommandRunner = run_command,
    transport: httpx.AsyncBaseTransport | None = None,
    timeout: float = TIMEOUT_S,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> dict:
    fetched_at = _iso(now())
    async with httpx.AsyncClient(transport=transport, timeout=timeout) as client:
        # the same order as SERVICE_IDS
        services = await asyncio.gather(
            _service("codex", "Codex", _codexbar("codex", env, run, timeout), fetched_at, timeout),
            _service("claude", "Claude Code", _codexbar("claude", env, run, timeout), fetched_at, timeout),
            _service("cursor", "Cursor Pro", _cursor(env, client), fetched_at, timeout),
            _service("commandcode", "Command Code", _command_code(env, client), fetched_at, timeout),
        )
    return {"fetchedAt": fetched_at, "services": list(services)}


def snapshot(env: Mapping[str, str] | None = None, **kwargs: Any) -> dict:
    """The usage snapshot, fetched now. Service failures are reported inside it, never raised."""
    return asyncio.run(collect(os.environ if env is None else env, **kwargs))


# --- cache -----------------------------------------------------------------------------------


def cache_path(env: Mapping[str, str]) -> Path:
    base = env.get("XDG_CACHE_HOME") or str(Path(env.get("HOME") or Path.home()) / ".cache")
    return Path(base) / "capability-router" / "usage.json"


def read_cache(env: Mapping[str, str], now: datetime, max_age_s: float = CACHE_MAX_AGE_S) -> dict | None:
    """The cached snapshot when it was fetched less than `max_age_s` ago, else None."""
    try:
        snap = json.loads(cache_path(env).read_text(encoding="utf-8"))
        fetched = datetime.fromisoformat(snap["fetchedAt"].replace("Z", "+00:00"))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
    if not isinstance(snap.get("services"), list):
        return None
    age = (now - fetched).total_seconds()
    return snap if 0 <= age < max_age_s else None


def write_cache(env: Mapping[str, str], snap: dict) -> None:
    """Best effort: a read-only or missing cache directory only means the next call fetches."""
    path = cache_path(env)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def cached_snapshot(
    env: Mapping[str, str] | None = None,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    max_age_s: float = CACHE_MAX_AGE_S,
    **kwargs: Any,
) -> tuple[dict, str]:
    """The snapshot and where it came from (`cache` or `fetched`). A fetch refreshes the cache."""
    env = os.environ if env is None else env
    cached = read_cache(env, now(), max_age_s)
    if cached is not None:
        return cached, "cache"
    snap = snapshot(env, now=now, **kwargs)
    write_cache(env, snap)
    return snap, "fetched"
