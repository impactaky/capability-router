"""pool.yaml, the services settings, usage standings, and how they steer the choice.

The synthetic pool (conftest) runs cheap-low on codex, near-cheap on cursor, mid-high on claude
and strong-max on claude and commandcode. With alpha=low every config passes, so the service
standings alone decide; with alpha=high only mid-high and strong-max pass.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
import yaml
from conftest import sync_pool

from capability_router import usage
from capability_router.availability import (
    ServiceSettings,
    Settings,
    load_settings,
    settings_path,
    standings,
)
from capability_router.cli import main
from capability_router.config import load_all, load_routing
from capability_router.jev import FixedLevels
from capability_router.scoring import TaskMeta, route
from capability_router.usage import cached_snapshot as real_cached_snapshot  # bound before conftest stubs it

SERVICES = ("codex", "claude", "cursor", "commandcode")
NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def window(period: str, remaining: int, resets_in: timedelta | None = None, **extra) -> dict:
    label = {"5h": "5h", "week": "週", "month": "月"}.get(period, period)
    resets = _iso(NOW + resets_in) if resets_in is not None else None
    w = {"label": label, "remainingPercent": remaining, "resetsAt": resets, "period": period}
    if period not in ("5h", "week", "month"):
        del w["period"]
    w.update(extra)
    return w


def week(used: int, elapsed_days: float) -> dict:
    """A week window `elapsed_days` in, with `used` % used: pace says elapsed/7 of it."""
    return window("week", 100 - used, timedelta(days=7 - elapsed_days))


def snapshot(**services) -> dict:
    out = []
    for sid, windows in services.items():
        if isinstance(windows, str):
            out.append({"id": sid, "status": windows, "message": "x", "windows": []})
        else:
            out.append({"id": sid, "status": "ok", "windows": windows})
    return {"fetchedAt": _iso(NOW), "services": out}


def _decide(root, levels, snap, settings=None, mode="cheap"):
    caps, models, services = load_routing()
    stand = standings(snap, settings or Settings(), SERVICES)
    return route(caps, models, FixedLevels(caps, levels).estimate("t"), TaskMeta(), mode=mode, services=services, standings=stand)


# --- pool.yaml ---------------------------------------------------------------------------------


def test_every_catalog_config_must_be_listed(root):
    pool = yaml.safe_load((root / "pool.yaml").read_text())
    del pool["configs"]["near-cheap"]
    (root / "pool.yaml").write_text(yaml.safe_dump(pool))
    with pytest.raises(ValueError, match="not listed: \\['near-cheap'\\]"):
        load_all()


@pytest.mark.parametrize(
    "entry, message",
    [
        ({"services": ["nowhere"]}, "unknown services"),
        ({"services": []}, "non-empty list"),
        ({"services": ["codex", "codex"]}, "listed twice"),
        ({"services": ["codex"], "enabled": "no"}, "true or false"),
        ({"services": ["codex"], "weight": 2}, "unknown keys"),
    ],
)
def test_bad_pool_entries_are_errors(root, entry, message):
    sync_pool(root, **{"near-cheap": entry})
    with pytest.raises(ValueError, match=message):
        load_all()


def test_a_config_not_in_the_catalog_is_an_error(root):
    pool = yaml.safe_load((root / "pool.yaml").read_text())
    pool["configs"]["ghost"] = {"services": ["codex"]}
    (root / "pool.yaml").write_text(yaml.safe_dump(pool))
    with pytest.raises(ValueError, match="not in models/"):
        load_all()


def test_a_missing_pool_file_is_an_error(root):
    (root / "pool.yaml").unlink()
    with pytest.raises(ValueError, match="pool.yaml not found") as exc:
        load_all()
    assert "CAPABILITY_ROUTER_POOL" in str(exc.value)
    assert str(root / "pool.yaml") in str(exc.value)


def test_disabled_configs_leave_the_pool_and_cannot_be_chosen(root):
    sync_pool(root, **{"strong-max": {"services": ["claude"], "enabled": False}})
    caps, models = load_all()
    assert "strong-max" not in {m.id for m in models}
    # alpha=high: the strongest enabled config is mid-high (0.75), so it is the only one that
    # clears the user's high threshold; the disabled strong-max is not a candidate.
    assert _decide(root, {"alpha": "high"}, None).chosen.id == "mid-high"


# --- the services settings ---------------------------------------------------------------------


def test_settings_default_without_a_file(tmp_path):
    s = load_settings(tmp_path / "missing.yaml", SERVICES)
    assert s.low_5h_percent == 5
    assert s.of("claude") == ServiceSettings()


def test_settings_path_follows_the_env_and_xdg():
    assert str(settings_path({"CAPABILITY_ROUTER_SERVICES": "/x/s.yaml"})) == "/x/s.yaml"
    assert str(settings_path({"XDG_CONFIG_HOME": "/cfg", "HOME": "/h"})) == "/cfg/capability-router/services.yaml"
    assert str(settings_path({"HOME": "/h"})) == "/h/.config/capability-router/services.yaml"


def test_settings_are_read_and_checked(tmp_path):
    path = tmp_path / "services.yaml"
    path.write_text("low_5h_percent: 10\nservices:\n  claude: {offset: -20}\n  codex: {ticket: true}\n")
    s = load_settings(path, SERVICES)
    assert s.low_5h_percent == 10
    assert s.of("claude") == ServiceSettings(offset=-20.0)
    assert s.of("codex") == ServiceSettings(ticket=True)
    for body, message in [
        ("services: {nowhere: {offset: 1}}\n", "unknown service"),
        ("services: {claude: {offset: lots}}\n", "offset must be a number"),
        ("services: {codex: {ticket: yes please}}\n", "ticket must be true or false"),
        ("services: {codex: {weight: 1}}\n", "only `offset` and `ticket`"),
        ("low_5h_percent: 200\n", "from 0 to 100"),
        ("tickets: []\n", "unknown keys"),
    ]:
        path.write_text(body)
        with pytest.raises(ValueError, match=message):
            load_settings(path, SERVICES)


# --- standings ---------------------------------------------------------------------------------


def test_week_surplus_is_pace_minus_used():
    # 3.5 of 7 days in: pace says 50% used. 30% used is 20 points ahead, 70% used is 20 behind.
    st = standings(snapshot(claude=[week(30, 3.5)], codex=[week(70, 3.5)]), Settings(), ["claude", "codex"])
    assert st["claude"].surplus == pytest.approx(20)
    assert st["codex"].surplus == pytest.approx(-20)
    assert st["claude"].tier == st["codex"].tier == "normal"


def test_month_window_starts_one_calendar_month_before_its_reset():
    # resets 2026-10-03 12:00 -> started 2026-09-03 12:00 (30 days); 20 of 30 days in = 66.7%.
    w = window("month", 90, timedelta(days=10))
    st = standings(snapshot(cursor=[w]), Settings(), ["cursor"])["cursor"]
    assert st.surplus == pytest.approx(100 * 20 / 30 - 10)


def test_the_tightest_week_or_month_window_sets_the_surplus_and_5h_does_not():
    windows = [window("5h", 40, timedelta(hours=1)), week(10, 3.5), window("month", 55, timedelta(days=15))]
    st = standings(snapshot(commandcode=windows), Settings(), ["commandcode"])["commandcode"]
    # week +40, month 15/30 = 50% pace with 45% used = +5
    assert st.base == pytest.approx(5, abs=0.5)
    assert st.tier == "normal"


def test_offset_is_added_to_the_surplus():
    settings = Settings(services={"claude": ServiceSettings(offset=-20)})
    st = standings(snapshot(claude=[week(30, 3.5)]), settings, ["claude"])["claude"]
    assert (st.base, st.offset, st.surplus) == (pytest.approx(20), -20, pytest.approx(0))


def test_ticket_uses_the_remaining_percent_of_the_week_window():
    settings = Settings(services={"codex": ServiceSettings(ticket=True)})
    st = standings(snapshot(codex=[week(70, 3.5)]), settings, ["codex"])["codex"]
    assert st.surplus == pytest.approx(30)  # not -20: the week is reset with a ticket


def test_zero_percent_on_any_window_exhausts_the_service():
    for windows in ([week(100, 3.5)], [window("5h", 0, timedelta(hours=2)), week(10, 3.5)]):
        st = standings(snapshot(codex=windows), Settings(), ["codex"])["codex"]
        assert st.tier == "exhausted"


def test_ticket_does_not_save_an_exhausted_week():
    settings = Settings(services={"codex": ServiceSettings(ticket=True)})
    assert standings(snapshot(codex=[week(100, 3.5)]), settings, ["codex"])["codex"].tier == "exhausted"


def test_low_5h_window_lowers_the_tier():
    windows = [window("5h", 5, timedelta(hours=2)), week(10, 3.5)]
    assert standings(snapshot(claude=windows), Settings(), ["claude"])["claude"].tier == "low_5h"
    windows[0] = window("5h", 6, timedelta(hours=2))
    assert standings(snapshot(claude=windows), Settings(), ["claude"])["claude"].tier == "normal"
    assert standings(snapshot(claude=windows), Settings(low_5h_percent=10), ["claude"])["claude"].tier == "low_5h"


def test_scoped_windows_are_ignored():
    windows = [week(10, 3.5), window("week", 0, timedelta(days=3), label="Fable only", scoped=True)]
    st = standings(snapshot(claude=windows), Settings(), ["claude"])["claude"]
    assert st.tier == "normal"
    assert st.surplus == pytest.approx(40)


def test_unknown_usage_counts_as_on_pace_with_the_offset():
    settings = Settings(services={"claude": ServiceSettings(offset=-20)})
    st = standings(snapshot(codex="error"), settings, ["codex", "claude"])
    assert (st["codex"].status, st["codex"].tier, st["codex"].surplus) == ("error", "normal", 0)
    assert (st["claude"].status, st["claude"].surplus) == ("missing", -20)
    skipped = standings(None, settings, ["claude"])["claude"]
    assert (skipped.status, skipped.surplus) == ("skipped", -20)


# --- choosing --------------------------------------------------------------------------------


def test_without_usage_the_mode_alone_decides(root):
    d = _decide(root, {"alpha": "low"}, None)
    assert (d.chosen.id, d.service) == ("cheap-low", "codex")


def test_the_service_with_the_largest_surplus_wins_over_a_cheaper_config(root):
    snap = snapshot(codex=[week(70, 3.5)], cursor=[week(20, 3.5)], claude=[week(40, 3.5)])
    d = _decide(root, {"alpha": "low"}, snap)
    assert (d.chosen.id, d.service) == ("near-cheap", "cursor")  # +30 beats claude +10, codex -20
    assert d.selection["service"] == {"chosen": "cursor", "tier": "normal", "surplus": 30.0, "tied_services": ["cursor"]}


def test_inside_the_service_the_mode_picks(root):
    snap = snapshot(claude=[week(0, 3.5)])  # claude +50, the rest unknown (0)
    assert _decide(root, {"alpha": "low"}, snap, mode="cheap").chosen.id == "mid-high"
    assert _decide(root, {"alpha": "low"}, snap, mode="best").chosen.id == "strong-max"


def test_offset_can_push_a_service_below_the_others(root):
    snap = snapshot(claude=[week(10, 3.5)], codex=[week(40, 3.5)])  # claude +40, codex +10
    assert _decide(root, {"alpha": "low"}, snap).service == "claude"
    settings = Settings(services={"claude": ServiceSettings(offset=-50)})
    assert _decide(root, {"alpha": "low"}, snap, settings).service == "codex"


def test_services_tied_on_surplus_are_compared_together(root):
    d = _decide(root, {"alpha": "low"}, snapshot(codex=[week(50, 3.5)], cursor=[week(50, 3.5)]))
    assert d.chosen.id == "cheap-low"  # codex and cursor both 0 (like the unknown ones): cheapest of all
    assert set(d.selection["service"]["tied_services"]) == {"codex", "cursor", "claude", "commandcode"}


def test_low_5h_goes_after_every_normal_service(root):
    snap = snapshot(cursor=[window("5h", 3, timedelta(hours=1)), week(0, 3.5)], codex=[week(80, 3.5)])
    d = _decide(root, {"alpha": "low"}, snap)
    assert d.service != "cursor"  # +50 but its 5h window is nearly empty
    assert d.standings["cursor"].tier == "low_5h"


def test_low_5h_is_still_chosen_when_it_is_all_that_passes(root):
    # alpha=high: only mid-high (claude) and strong-max (claude, commandcode) pass.
    low = [window("5h", 3, timedelta(hours=1)), week(0, 3.5)]
    d = _decide(root, {"alpha": "high"}, snapshot(claude=low, commandcode=low))
    assert d.chosen.id in {"mid-high", "strong-max"}
    assert d.selection["service"]["tier"] == "low_5h"


def test_an_exhausted_service_is_never_chosen_and_says_why(root):
    d = _decide(root, {"alpha": "low"}, snapshot(codex=[week(100, 3.5)]))
    assert d.service != "codex"
    cand = next(c for c in d.candidates if c.config.id == "cheap-low")
    assert not cand.passed
    assert any("no service left" in r and "週 0% left" in r for r in cand.reasons)


def test_a_config_on_two_services_survives_one_being_exhausted(root):
    d = _decide(root, {"alpha": "high"}, snapshot(claude=[week(100, 3.5)]))
    assert (d.chosen.id, d.service) == ("strong-max", "commandcode")
    assert not d.fallback  # usage never relaxes the requirements


def test_everything_exhausted_routes_nothing_without_relaxing(root):
    gone = [week(100, 3.5)]
    d = _decide(root, {"alpha": "high"}, snapshot(codex=gone, claude=gone, cursor=gone, commandcode=gone))
    assert d.chosen is None and d.service is None
    assert d.relaxations == []


# --- the CLI -----------------------------------------------------------------------------------


def _write_snapshot(tmp_path, snap) -> str:
    path = tmp_path / "usage.json"
    path.write_text(json.dumps(snap), encoding="utf-8")
    return str(path)


def test_route_prints_config_and_service_from_a_usage_file(root, tmp_path, capsys):
    snap = _write_snapshot(tmp_path, snapshot(cursor=[week(0, 3.5)]))
    assert main(["route", "--levels", "alpha=low", "--usage-file", snap, "t"]) == 0
    assert capsys.readouterr().out.strip() == "near-cheap cursor"


def test_route_reads_the_offsets_from_the_settings_file(root, tmp_path, monkeypatch, capsys):
    settings = tmp_path / "services.yaml"
    settings.write_text("services: {codex: {offset: -10}}\n")
    monkeypatch.setenv("CAPABILITY_ROUTER_SERVICES", str(settings))
    assert main(["route", "--levels", "alpha=low", "--mode", "cheap", "--no-usage", "t"]) == 0
    assert capsys.readouterr().out.strip() == "near-cheap cursor"  # codex pushed below the rest


def test_route_explain_reports_services_and_usage_source(root, tmp_path, capsys):
    snap = _write_snapshot(tmp_path, snapshot(codex="unavailable", claude=[week(100, 3.5)]))
    assert main(["route", "--levels", "alpha=low", "--usage-file", snap, "--explain", "t"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["usage_source"] == "file"
    assert out["service"] is not None
    by_id = {s["service"]: s for s in out["services"]}
    assert by_id["claude"]["tier"] == "exhausted"
    assert by_id["codex"]["status"] == "unavailable"
    assert out["services"][-1]["service"] == "claude"  # exhausted services come last
    row = next(r for r in out["ranking"] if r["config"] == "strong-max")
    assert row["services"] == ["claude", "commandcode"] and row["available_services"] == ["commandcode"]


def test_route_reads_usage_through_the_cache(root, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(usage, "cached_snapshot", lambda *a, **k: calls.append(1) or (snapshot(), "cache"))
    assert main(["route", "--levels", "alpha=low", "--explain", "t"]) == 0
    assert json.loads(capsys.readouterr().out)["usage_source"] == "cache"
    assert calls == [1]
    assert main(["route", "--levels", "alpha=low", "--no-usage", "t"]) == 0
    assert calls == [1]  # --no-usage never reads it


def test_route_exits_1_when_every_service_is_exhausted(root, tmp_path, capsys):
    gone = [week(100, 3.5)]
    snap = _write_snapshot(tmp_path, snapshot(codex=gone, claude=gone, cursor=gone, commandcode=gone))
    assert main(["route", "--levels", "alpha=low", "--usage-file", snap, "t"]) == 1
    assert "no routable config" in capsys.readouterr().err


def test_models_lists_the_pool_and_its_services(root, capsys):
    sync_pool(root, **{"cheap-low": {"services": ["codex"], "enabled": False}})
    assert main(["models"]) == 0
    out = capsys.readouterr().out
    assert "pool: 3 of 4 configs in the catalog are enabled" in out
    assert "disabled: cheap-low" in out
    assert any(ln.split() == ["strong-max", "claude,", "commandcode"] for ln in out.splitlines())


# --- the cache -------------------------------------------------------------------------------


def test_cache_is_fresh_for_five_minutes(tmp_path):
    env = {"XDG_CACHE_HOME": str(tmp_path)}
    snap = {"fetchedAt": _iso(NOW), "services": []}
    usage.write_cache(env, snap)
    assert (tmp_path / "capability-router" / "usage.json").exists()
    assert usage.read_cache(env, NOW + timedelta(minutes=4)) == snap
    assert usage.read_cache(env, NOW + timedelta(minutes=5)) is None
    assert usage.read_cache({"XDG_CACHE_HOME": str(tmp_path / "none")}, NOW) is None


def test_cached_snapshot_fetches_once_and_then_reads_the_cache(tmp_path, monkeypatch):
    env = {"XDG_CACHE_HOME": str(tmp_path)}
    fetches = []

    def fetch(env, now, **kwargs):
        fetches.append(1)
        return {"fetchedAt": _iso(now()), "services": []}

    monkeypatch.setattr(usage, "snapshot", fetch)
    assert real_cached_snapshot(env, now=lambda: NOW)[1] == "fetched"
    assert real_cached_snapshot(env, now=lambda: NOW + timedelta(minutes=1))[1] == "cache"
    assert real_cached_snapshot(env, now=lambda: NOW + timedelta(minutes=6))[1] == "fetched"
    assert len(fetches) == 2


def test_write_cache_ignores_an_unwritable_directory(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    usage.write_cache({"XDG_CACHE_HOME": str(blocker)}, {"fetchedAt": _iso(NOW), "services": []})
