"""The delegation log: what `route` chose, and how the delegation ended.

Every `route` call appends one `route` record to a JSONL file, and the caller later appends
`outcome` records to the same id with `log outcome` (pass / fail / abandoned, how long it took,
how many send-backs, who did the work). `log` summarizes the file by config and service.

Routing never reads the log: the log is a record for the caller, not feedback into selection.

The file is `${XDG_STATE_HOME:-~/.local/state}/capability-router/delegations.jsonl`, resolved the
same way as `config.models_dir`. `CAPABILITY_ROUTER_LOG` overrides the path; the value `off`
turns logging off. Appending takes `fcntl.flock` so two callers can write at once.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping


VERSION = 1
_SINCE = re.compile(r"(\d+)([dhm])")


def log_path(env: Mapping[str, str] | None = None) -> Path | None:
    """The delegation log file, or None when `CAPABILITY_ROUTER_LOG` is `off`.

    `$CAPABILITY_ROUTER_LOG` wins; otherwise the XDG state default, the same way
    `config.models_dir` resolves the catalog directory.
    """
    env = os.environ if env is None else env
    value = env.get("CAPABILITY_ROUTER_LOG")
    if value == "off":
        return None
    if value:
        return Path(value)
    state = env.get("XDG_STATE_HOME") or str(Path(env.get("HOME") or Path.home()) / ".local" / "state")
    return Path(state) / "capability-router" / "delegations.jsonl"


def iso_now(now: datetime | None = None) -> str:
    """UTC ISO 8601 without microseconds (`2026-09-24T01:23:45Z`)."""
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id() -> str:
    """A short id. A collision is harmless: records are matched by exact id, not hash."""
    return uuid.uuid4().hex[:12]


def parse_since(text: str, now: datetime | None = None) -> datetime:
    """`7d` / `24h` / `30m` before now, or a `YYYY-MM-DD` date at midnight UTC."""
    text = text.strip()
    m = _SINCE.fullmatch(text)
    if m:
        n = int(m.group(1))
        unit = {"d": timedelta(days=n), "h": timedelta(hours=n), "m": timedelta(minutes=n)}[m.group(2)]
        return (now or datetime.now(timezone.utc)) - unit
    try:
        return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        raise ValueError(f"bad --since {text!r}; expected 7d, 24h, 30m or YYYY-MM-DD") from None


def route_record(
    *,
    decision,
    task: str,
    label: str | None,
    include_task: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The route record for one `route` call (`decision` is scoring.Decision).

    Only what later review needs: what was asked (`mode`, the non-`none` levels), what was picked,
    whether the pick had to relax the requirement (`fallback`), and the expected cost and time to
    compare with the outcome. `--explain` stays the way to see the full decision.
    """
    chosen = decision.selection.get("chosen") or {}
    record: dict[str, Any] = {
        "type": "route",
        "version": VERSION,
        "id": new_id(),
        "ts": iso_now(now),
        "label": label,
    }
    if include_task:
        record["task"] = task
    record.update(
        {
            "mode": decision.mode,
            "levels": {item: level for item, level in decision.levels.items() if level != "none"},
            "chosen": decision.chosen.id if decision.chosen else None,
            "service": decision.service,
            "fallback": decision.fallback,
            "cost": _round(chosen.get("cost"), 6),
            "time_per_task_s": _round(chosen.get("time_per_task_s"), 1),
        }
    )
    return record


def _round(value: Any, digits: int) -> float | None:
    return None if value is None else round(float(value), digits)


def outcome_record(
    *,
    id: str,
    status: str,
    duration_s: float | None,
    rounds: int | None,
    implementer: str | None,
    note: str | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The outcome record for one `log outcome` call."""
    return {
        "type": "outcome",
        "version": VERSION,
        "id": id,
        "ts": iso_now(now),
        "status": status,
        "duration_s": duration_s,
        "rounds": rounds,
        "implementer": implementer,
        "note": note,
    }


def append_record(path: Path, record: dict[str, Any]) -> None:
    """Append one JSON line under `fcntl.flock`, creating the directory if needed.

    The caller treats any failure as a warning: a missing log never fails a route.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with open(path, "a", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.write(line)  # one write
            f.flush()
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def read_records(path: Path) -> tuple[list[dict[str, Any]], int]:
    """The parsed records and the number of malformed lines skipped.

    A line is malformed when it is not JSON, or is not an object with a `type`. Blank lines are
    not counted. A missing file is zero records, not an error.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return [], 0
    records: list[dict[str, Any]] = []
    skipped = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        if not isinstance(record, dict) or "type" not in record:
            skipped += 1
            continue
        records.append(record)
    return records, skipped


def parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else None


def summarize(records: list[dict[str, Any]], cutoff: datetime | None = None) -> dict[str, Any]:
    """Group route records by (chosen config, service) and fold in their last outcome.

    `cutoff` filters route records by `ts`; outcomes are then matched to the surviving ids.
    An outcome with no route record, or a route record with no outcome, is simply absent from
    the group's numbers. `pass_rate`, `median_duration_s` and `median_rounds` are None when the
    group has no outcome to read.
    """
    routes: list[dict[str, Any]] = []
    outcomes: dict[Any, list[dict[str, Any]]] = {}
    for record in records:
        if record.get("type") == "route":
            if cutoff is not None:
                ts = parse_ts(record.get("ts"))
                if ts is None or ts < cutoff:
                    continue
            routes.append(record)
        elif record.get("type") == "outcome":
            outcomes.setdefault(record.get("id"), []).append(record)

    groups: dict[tuple, list[dict[str, Any]]] = {}
    for route in routes:
        groups.setdefault((route.get("chosen"), route.get("service")), []).append(route)

    rows = []
    for (chosen, service), group in groups.items():
        last = [outcomes[r.get("id")][-1] for r in group if outcomes.get(r.get("id"))]
        rows.append(
            {
                "chosen": chosen,
                "service": service,
                "routes": len(group),
                **_outcome_stats(last),
            }
        )
    rows.sort(key=lambda r: (str(r["chosen"]), str(r["service"])))
    all_outcomes = [outcomes[r.get("id")][-1] for r in routes if outcomes.get(r.get("id"))]
    return {
        "groups": rows,
        "total": {"routes": len(routes), **_outcome_stats(all_outcomes)},
    }


def _outcome_stats(last: list[dict[str, Any]]) -> dict[str, Any]:
    if not last:
        return {
            "outcomes": 0,
            "pass_rate": None,
            "median_duration_s": None,
            "median_rounds": None,
        }
    passed = sum(1 for o in last if o.get("status") == "pass")
    return {
        "outcomes": len(last),
        "pass_rate": 100.0 * passed / len(last),
        "median_duration_s": _median([o.get("duration_s") for o in last]),
        "median_rounds": _median([o.get("rounds") for o in last]),
    }


def _median(values: list[Any]) -> float | None:
    numbers = [float(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if not numbers:
        return None
    numbers.sort()
    mid = len(numbers) // 2
    if len(numbers) % 2:
        return numbers[mid]
    return (numbers[mid - 1] + numbers[mid]) / 2
