"""How far each service is ahead of its pace, and whether it may be chosen at all.

A service's standing comes from a usage snapshot (usage.py) and the personal services settings
(`services.yaml` under the XDG config directory). Nothing here names a service: the ids are
whatever the snapshot and `pool.yaml` carry.

- `exhausted`: some window (other than a scoped one) has 0% left. The service is never chosen.
- `low_5h`: the 5h window has at most `low_5h_percent` left. Chosen only when no `normal`
  service has a passing config.
- `normal`: everything else.

Within a tier the service with the larger surplus comes first. A window's surplus is its pace
(expected used % = elapsed share of the window) minus what is actually used, in percentage
points. The service's surplus is the smallest surplus over its week and month windows plus its
`offset`; 5h windows only decide `low_5h`. With `ticket: true` a week window's surplus is its
remaining % (the human resets it with a ticket when it runs out). Scoped windows (a limit on some
models of the service only) are ignored. A service whose usage could not be read counts as on
pace (surplus 0 + offset).
"""

from __future__ import annotations

import calendar
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

DEFAULT_LOW_5H_PERCENT = 5.0
TIERS = ("normal", "low_5h", "exhausted")
TIER_RANK = {"normal": 0, "low_5h": 1}  # `exhausted` is never ranked


@dataclass(frozen=True)
class ServiceSettings:
    offset: float = 0.0  # percentage points added to the surplus (negative = chosen less)
    ticket: bool = False  # a reset ticket will be used when the week window runs out


@dataclass(frozen=True)
class Settings:
    low_5h_percent: float = DEFAULT_LOW_5H_PERCENT
    services: dict[str, ServiceSettings] = field(default_factory=dict)

    def of(self, service: str) -> ServiceSettings:
        return self.services.get(service, ServiceSettings())


def settings_path(env: Mapping[str, str]) -> Path:
    if env.get("CAPABILITY_ROUTER_SERVICES"):
        return Path(env["CAPABILITY_ROUTER_SERVICES"])
    config = env.get("XDG_CONFIG_HOME") or str(Path(env.get("HOME") or Path.home()) / ".config")
    return Path(config) / "capability-router" / "services.yaml"


def load_settings(path: Path, known_services: Iterable[str]) -> Settings:
    """`low_5h_percent: 5` and `services: {<id>: {offset: -20, ticket: true}}`. No file = defaults."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return Settings()
    where = str(path)
    if not isinstance(data, dict):
        raise ValueError(f"{where}: must be a mapping")
    extra = sorted(set(data) - {"low_5h_percent", "services"})
    if extra:
        raise ValueError(f"{where}: unknown keys {extra}")
    low = data.get("low_5h_percent", DEFAULT_LOW_5H_PERCENT)
    if isinstance(low, bool) or not isinstance(low, (int, float)) or not 0 <= low <= 100:
        raise ValueError(f"{where}: low_5h_percent must be a number from 0 to 100, got {low!r}")
    services_spec = data.get("services") or {}
    if not isinstance(services_spec, dict):
        raise ValueError(f"{where}: `services` must be a mapping of service id to its settings")
    known = tuple(known_services)
    services: dict[str, ServiceSettings] = {}
    for sid, spec in services_spec.items():
        if sid not in known:
            raise ValueError(f"{where}: unknown service {sid!r}; expected some of {list(known)}")
        spec = spec or {}
        if not isinstance(spec, dict) or set(spec) - {"offset", "ticket"}:
            raise ValueError(f"{where}: {sid} takes only `offset` and `ticket`")
        offset = spec.get("offset", 0)
        if isinstance(offset, bool) or not isinstance(offset, (int, float)) or not math.isfinite(offset):
            raise ValueError(f"{where}: {sid} offset must be a number, got {offset!r}")
        ticket = spec.get("ticket", False)
        if not isinstance(ticket, bool):
            raise ValueError(f"{where}: {sid} ticket must be true or false")
        services[sid] = ServiceSettings(offset=float(offset), ticket=ticket)
    return Settings(low_5h_percent=float(low), services=services)


def default_settings(known_services: Iterable[str], env: Mapping[str, str] | None = None) -> Settings:
    return load_settings(settings_path(os.environ if env is None else env), known_services)


@dataclass
class Standing:
    service: str | None
    status: str  # the snapshot's status, `missing` (not in it) or `skipped` (usage not read)
    tier: str
    base: float  # surplus before the offset
    offset: float
    ticket: bool
    windows: list[dict] = field(default_factory=list)
    reason: str | None = None

    @property
    def surplus(self) -> float:
        return self.base + self.offset

    @property
    def rank_key(self) -> tuple[int, float]:
        return TIER_RANK[self.tier], -self.surplus

    def to_dict(self) -> dict:
        return {
            "service": self.service,
            "status": self.status,
            "tier": self.tier,
            "surplus": round(self.surplus, 1),
            "base": round(self.base, 1),
            "offset": self.offset,
            "ticket": self.ticket,
            "windows": self.windows,
            "reason": self.reason,
        }


def neutral(service: str | None, status: str = "skipped", settings: Settings | None = None) -> Standing:
    s = (settings or Settings()).of(service) if service else ServiceSettings()
    return Standing(service=service, status=status, tier="normal", base=0.0, offset=s.offset, ticket=s.ticket)


def standings(snapshot: dict | None, settings: Settings, services: Iterable[str]) -> dict[str, Standing]:
    """The standing of every service in `services`, read from `snapshot` (None = usage not read)."""
    by_id = {}
    if snapshot is not None:
        by_id = {s.get("id"): s for s in snapshot.get("services") or [] if isinstance(s, dict)}
    now = _parse_time(snapshot.get("fetchedAt")) if snapshot else None
    out: dict[str, Standing] = {}
    for sid in dict.fromkeys(services):
        if snapshot is None:
            out[sid] = neutral(sid, "skipped", settings)
            continue
        svc = by_id.get(sid)
        if svc is None:
            st = neutral(sid, "missing", settings)
            st.reason = "not in the usage snapshot; counted as on pace"
        elif svc.get("status") != "ok" or now is None:
            st = neutral(sid, str(svc.get("status") or "error"), settings)
            st.reason = "usage unknown; counted as on pace"
        else:
            st = _standing(sid, svc.get("windows") or [], now, settings)
        out[sid] = st
    return out


def _standing(sid: str, windows: list, now: datetime, settings: Settings) -> Standing:
    cfg = settings.of(sid)
    tier = "normal"
    reason = None
    surpluses: list[float] = []
    rows: list[dict] = []
    for w in windows:
        if not isinstance(w, dict):
            continue
        remaining = w.get("remainingPercent")
        if isinstance(remaining, bool) or not isinstance(remaining, (int, float)):
            continue
        period = w.get("period")
        row: dict[str, Any] = {"label": w.get("label"), "period": period, "remainingPercent": remaining}
        rows.append(row)
        if w.get("scoped"):
            row["counted"] = "ignored (scoped)"
            continue
        if remaining <= 0:
            tier, reason = "exhausted", f"{w.get('label')} 0% left"
        if period == "5h":
            row["counted"] = "5h"
            if tier == "normal" and remaining <= settings.low_5h_percent:
                tier, reason = "low_5h", f"5h {remaining}% left (<= {settings.low_5h_percent:g}%)"
            continue
        if period not in ("week", "month"):
            row["counted"] = "0% check only"
            continue
        if cfg.ticket and period == "week":
            row["counted"] = "ticket: remaining"
            row["surplus"] = float(remaining)
            surpluses.append(float(remaining))
            continue
        expected = _expected_used(period, _parse_time(w.get("resetsAt")), now)
        if expected is None:
            row["counted"] = "no reset time"
            continue
        surplus = expected - (100 - remaining)
        row.update(counted="pace", expectedUsedPercent=round(expected, 1), surplus=round(surplus, 1))
        surpluses.append(surplus)
    return Standing(
        service=sid,
        status="ok",
        tier=tier,
        base=min(surpluses) if surpluses else 0.0,
        offset=cfg.offset,
        ticket=cfg.ticket,
        windows=rows,
        reason=reason,
    )


def _expected_used(period: str, resets_at: datetime | None, now: datetime) -> float | None:
    """The used % a steady pace would have reached by `now`: the elapsed share of the window."""
    if resets_at is None:
        return None
    start = resets_at - timedelta(days=7) if period == "week" else _month_before(resets_at)
    length = (resets_at - start).total_seconds()
    if length <= 0:
        return None
    return 100 * min(1.0, max(0.0, (now - start).total_seconds() / length))


def _month_before(dt: datetime) -> datetime:
    year, month = (dt.year, dt.month - 1) if dt.month > 1 else (dt.year - 1, 12)
    return dt.replace(year=year, month=month, day=min(dt.day, calendar.monthrange(year, month)[1]))


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else None
