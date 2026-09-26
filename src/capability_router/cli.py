"""capability-router CLI.

  capability-router route [--mode best|balanced|cheap|fast-balanced] [--explain] "task text"   (or task on stdin)
  capability-router route --levels coding=high,long_context=mid "task"
  capability-router route --levels ... --no-usage "task"   (offline: no usage, every service level)
  capability-router models [--detail | --costs]
  capability-router sanity [--mode balanced] [--json]
  capability-router criteria [--output PATH]
  capability-router usage [--json]
  capability-router log [--since 7d|24h|30m|YYYY-MM-DD] [--json]
  capability-router log outcome <id> --status pass|fail|abandoned [--duration <秒>] [--rounds <n>]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

from rich.cells import cell_len
from rich.console import Console
from rich.table import Table
from rich.text import Text

from . import __version__, delegation_log
from .availability import default_settings, standings
from .config import (
    Capabilities,
    ModelConfig,
    capabilities_path,
    criteria_path,
    load_capabilities,
    load_models,
    load_pool,
    load_routing,
    load_sanity,
    models_dir,
    pool_path,
    sanity_path,
)
from .jev import FixedLevels, FixtureJev, JevClient, parse_levels
from .normalize import item_cost_per_task, item_scores, item_time_per_task
from .scoring import MODES, TaskMeta, estimate_tokens, route

# Free-text columns may wrap, but never below this many display columns: a narrow terminal must
# not stack one character per line, and a table that then does not fit may grow past the width.
_MIN_FREETEXT_WIDTH = 12

# The fixed shared rules at the top of every generated criteria.md.
CRITERIA_RULES = (
    "For each task, rate every item as none, low, mid, or high.",
    "A level means the task is about as demanding as that level's examples, when they are given.",
    "Choose the lowest sufficient level for each item. Do not raise a level by impression alone.",
    "Base levels on the task's deliverable.",
    "Reading and following the task instructions, order, or acceptance criteria is not a requirement under any item.",
    "Do not inspect config scores in the catalog or `capability-router models` output (including `--detail`) until the estimate is complete.",
)

_CRITERIA_HASH_RE = re.compile(r"^<!-- capability-router criteria: sha256=([0-9a-f]{64}) -->\s*$")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="capability-router", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("route", help="pick a model config for a task")
    r.add_argument("task", nargs="?", help="task text; read from stdin when omitted")
    r.add_argument("--mode", choices=MODES, default="balanced")
    r.add_argument("--explain", action="store_true", help="print full JSON decision instead of the config id")
    r.add_argument("--levels", help="skip Jev; comma-separated item=level (e.g. coding=high,long_context=mid)")
    r.add_argument("--jev-fixture", type=Path, help="skip the network; replay a recorded Jev response JSON")
    r.add_argument("--has-image", action="store_true", help="task includes image input (filters non-vision configs)")
    r.add_argument("--input-tokens", type=int, help="override the estimated input token count")
    r.add_argument("--no-usage", action="store_true", help="do not read usage: every service stands on pace (offsets still apply)")
    r.add_argument("--usage-file", type=Path, help="read the usage snapshot from this JSON (the `usage --json` shape) instead of fetching")
    r.add_argument("--label", help="a short label for this delegation, stored in the log")
    r.add_argument("--no-log", action="store_true", help="do not append a record to the delegation log")
    r.add_argument("--print-log-id", action="store_true", help="print `<config> <service> <log-id>` (log-id is `-` when not written)")

    m = sub.add_parser("models", help="list model configs and their item values")
    mode = m.add_mutually_exclusive_group()
    mode.add_argument("--detail", action="store_true", help="show the item scores, thresholds and kinds instead of the H/M/L summary")
    mode.add_argument("--costs", action="store_true", help="show the per-item cost and time per task instead of the item scores")

    s = sub.add_parser("sanity", help="route the fixed level cases in sanity.yaml and show the assignments")
    s.add_argument("--mode", choices=MODES, default="balanced")
    s.add_argument("--json", action="store_true", help="emit JSON instead of a table")

    c = sub.add_parser("criteria", help="generate the LLM-facing criteria.md from the capability definition")
    c.add_argument("--output", help="write here instead of criteria.md beside the definition; `-` for stdout")

    u = sub.add_parser("usage", help="show the remaining usage of the AI services")
    u.add_argument("--json", action="store_true", help="emit the usage snapshot as JSON instead of a table")

    lg = sub.add_parser("log", help="show the delegation log, or append an outcome to it")
    lg.add_argument("--since", help="only route records newer than 7d / 24h / 30m, or a YYYY-MM-DD date")
    lg.add_argument("--json", action="store_true", help="emit the summary as JSON instead of a table")
    lgs = lg.add_subparsers(dest="log_cmd")
    lo = lgs.add_parser("outcome", help="append an outcome for a delegation id")
    lo.add_argument("id", help="the log id `route --print-log-id` printed")
    lo.add_argument("--status", required=True, choices=("pass", "fail", "abandoned"))
    lo.add_argument("--duration", type=float, help="seconds; default: now minus the route record's ts")
    lo.add_argument("--rounds", type=int, help="number of send-backs to the implementer")
    lo.add_argument("--implementer", help="who actually did the work, e.g. `kind:args`")
    lo.add_argument("--note")
    return p


def make_estimator(caps, args):
    if getattr(args, "levels", None):
        return FixedLevels(caps, parse_levels(args.levels))
    if getattr(args, "jev_fixture", None):
        return FixtureJev(caps, args.jev_fixture)
    return JevClient(caps)


def cmd_route(args) -> int:
    caps, models, services = load_routing()
    stale = _criteria_warning(capabilities_path())
    if stale:
        print(stale, file=sys.stderr)
    task = args.task if args.task is not None else sys.stdin.read()
    task = task.strip()
    if not task:
        print("error: empty task", file=sys.stderr)
        return 2
    estimator = make_estimator(caps, args)
    estimates = estimator.estimate(task)
    meta = TaskMeta(has_image=args.has_image, input_tokens=args.input_tokens if args.input_tokens is not None else estimate_tokens(task))
    snap, source = _usage_snapshot(args)
    from .usage import SERVICE_IDS

    used = {sid for svc in services.values() for sid in svc}
    stand = standings(snap, default_settings(SERVICE_IDS), [sid for sid in SERVICE_IDS if sid in used])
    decision = route(caps, models, estimates, meta, mode=args.mode, services=services, standings=stand)
    log_id = _write_route_log(args, decision, estimator.name, task, meta, source)
    if args.explain:
        out = decision.to_dict()
        out["estimator"] = estimator.name
        out["task_tokens_estimate"] = meta.input_tokens
        out["usage_source"] = source
        out["usage_fetched_at"] = snap.get("fetchedAt") if snap else None
        out["log_id"] = log_id
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        if decision.chosen is None:
            print("error: no routable config", file=sys.stderr)
            return 1
        if args.print_log_id:
            print(f"{decision.chosen.id} {decision.service} {log_id or '-'}")
        else:
            print(f"{decision.chosen.id} {decision.service}")
    return 0 if decision.chosen is not None else 1


def _write_route_log(args, decision, estimator: str, task: str, meta, usage_source: str) -> str | None:
    """Append the route record, returning its id, or None when nothing was written.

    A missing or unwritable log is a warning, never a route failure: the chosen config and
    service are the answer, and recording them is best-effort.
    """
    if args.no_log:
        return None
    path = delegation_log.log_path()
    if path is None:
        return None
    record = delegation_log.route_record(
        decision=decision,
        task=task,
        label=args.label,
        include_task=os.environ.get("CAPABILITY_ROUTER_LOG_TASK") == "1",
    )
    try:
        delegation_log.append_record(path, record)
    except OSError as e:
        print(f"warning: delegation log not written: {e}", file=sys.stderr)
        return None
    return record["id"]


def _usage_snapshot(args) -> tuple[dict | None, str]:
    """The snapshot route reads, and where it came from: `file`, `cache`, `fetched` or `none`."""
    if args.no_usage:
        return None, "none"
    if args.usage_file:
        snap = json.loads(args.usage_file.read_text(encoding="utf-8"))
        if not isinstance(snap, dict) or not isinstance(snap.get("services"), list):
            raise ValueError(f"{args.usage_file}: not a usage snapshot")
        return snap, "file"
    from . import usage  # imported lazily: only a real fetch needs httpx

    return usage.cached_snapshot()


def _criteria_warning(caps_path: Path) -> str | None:
    """One warning line when a criteria.md beside the definition no longer matches it.

    The warning never stops a route. A missing criteria.md produces nothing.
    """
    criteria = criteria_path(caps_path)
    try:
        first = criteria.read_text(encoding="utf-8").splitlines()[0]
    except FileNotFoundError:
        return None
    except (OSError, IndexError):
        return f"warning: {criteria} is unreadable; regenerate it with `capability-router criteria`"
    match = _CRITERIA_HASH_RE.match(first)
    if match and match.group(1) == hashlib.sha256(caps_path.read_bytes()).hexdigest():
        return None
    return (
        f"warning: {criteria} is stale (it does not match {caps_path}); "
        "regenerate it with `capability-router criteria`"
    )


def render_criteria(caps: Capabilities, caps_path: Path) -> str:
    """The LLM-facing Markdown for the definition, headed by its source sha256."""
    digest = hashlib.sha256(caps_path.read_bytes()).hexdigest()
    lines = [
        f"<!-- capability-router criteria: sha256={digest} -->",
        "",
        "# capability-router estimation criteria",
        "",
        *CRITERIA_RULES,
        "",
    ]
    for item in caps.items.values():
        lines.append(f"### {item.name}")
        lines.append(f"Measures: {item.measures}")
        lines.append(f"Excludes: {item.excludes}")
        for level in caps.levels:
            lines.append(f"- {level}: {item.levels[level]}")
            for example in item.examples.get(level, ()):
                lines.append(f"  - e.g. {example}")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def cmd_criteria(args) -> int:
    path = capabilities_path()
    caps = load_capabilities(path)
    text = render_criteria(caps, path)
    if args.output == "-":
        sys.stdout.write(text)
        return 0
    out = Path(args.output) if args.output else criteria_path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(out)
    return 0


def cmd_models(args) -> int:
    caps, models, services = load_routing()
    items = list(caps.items)
    if args.costs:
        return _print_costs(caps, models, items)
    if args.detail:
        return _print_detail(caps, models, services, items)
    return _print_summary(caps, models, services, items)


def _print_summary(caps, models, services: dict[str, tuple[str, ...]], items: list[str]) -> int:
    """The default `models` view: each config's item performance as H/M/L, and where it runs.

    A `level` item shows its catalog letter directly. A `score` item shows the highest level whose
    threshold the score clears (the same comparison the router's filter uses): `H`, `M`, `L` or
    `-` below low. `?` is a config that has no value for the item.
    """
    short = [_abbrev(i) for i in items]
    rows = [[m.id] + [_grade(caps, m, item) for item in items] for m in models]
    _print_table(["config", *short], rows, right=range(1, len(short) + 1))
    _print_text(_items_legend(short, items))
    _print_text("H/M/L = clears the high/mid/low level, - = below low, ? = no value")
    _print_pool(services)
    return 0


def _grade(caps: Capabilities, cfg: ModelConfig, item: str) -> str:
    """`H`/`M`/`L`/`-` for the config on the item, or `?` when it has no value."""
    value = cfg.value(item)
    if value is None:
        return "?"
    if value.by_level:
        return value.level  # type: ignore[return-value]
    thresholds = caps.items[item].thresholds
    if value.score is None or thresholds is None:
        return "?"
    for letter, level in (("H", "high"), ("M", "mid"), ("L", "low")):
        if value.score >= thresholds[level]:
            return letter
    return "-"


def _print_detail(caps, models, services: dict[str, tuple[str, ...]], items: list[str]) -> int:
    """`models --detail`: the numeric item scores, their thresholds and each item's kind."""
    short = [_abbrev(i) for i in items]
    scores = [item_scores(caps, m) for m in models]
    header = ["config", *short]
    rows = [[m.id] + [_fmt(sc[i], 3) for i in items] for m, sc in zip(models, scores)]
    for level in ("low", "mid", "high"):
        row = [f"threshold {level}"]
        for item in items:
            spec = caps.items[item].thresholds
            row.append(_fmt(spec[level] if spec else None, 3))
        rows.append(row)
    _print_table(header, rows, right=range(1, len(header)))
    _print_text("\nkind per item: score = read a `score`, level = read a `level`.")
    _print_table(
        header,
        [[m.id] + [_kind(caps, m, i) for i in items] for m in models],
    )
    _print_text(
        "score = a catalog score, or a catalog level put on its threshold ladder"
        " (H/M/L = high/mid/low threshold, or 1.0 / 2/3 / 1/3 when the item has no thresholds;"
        " - = 0). thresholds = the definition's per-item thresholds;"
        " `-` means the item is decided by level alone."
    )
    _print_text(_items_legend(short, items))
    _print_pool(services)
    return 0


def _kind(caps: Capabilities, cfg: ModelConfig, item: str) -> str:
    value = cfg.value(item)
    if value is None:
        return "-"
    return "level" if value.by_level else "score"


def _items_legend(short: list[str], items: list[str]) -> str:
    """`c=coding, ...`: what the abbreviated item columns stand for."""
    return "items: " + ", ".join(f"{s}={i}" for s, i in zip(short, items))


def _print_pool(services: dict[str, tuple[str, ...]]) -> None:
    """Which configs of the catalog are in the pool, and where each one runs (pool.yaml)."""
    from .usage import SERVICE_IDS

    catalog = [c.id for c in load_models(models_dir())]
    disabled = [cid for cid, e in load_pool(pool_path(), catalog, SERVICE_IDS).items() if not e.enabled]
    _print_text(f"\npool: {len(services)} of {len(catalog)} configs in the catalog are enabled (pool.yaml).")
    if disabled:
        _print_text("disabled: " + ", ".join(disabled))
    _print_table(["config", "services"], [[cid, ", ".join(svc)] for cid, svc in services.items()])


def _print_costs(caps, models, items: list[str]) -> int:
    """Cost and seconds per task, per item: what `balanced`/`cheap` and `fast-balanced` compare.

    Item columns are abbreviated to the item's initials, the same way the sanity table does it.
    """
    short = [_abbrev(i) for i in items]
    _print_text(
        "cost per task, by item. Selection cost = sum over the items the request asks for;"
        " when it asks for none, the sum over every item above."
    )
    rows = []
    for m in models:
        c = item_cost_per_task(caps, m)
        rows.append([m.id] + [_fmt(c[i], 4) for i in items])
    _print_table(["config", *short], rows, right=range(1, len(short) + 1))
    _print_text("\ntime per task (seconds), by item. Only --mode fast-balanced selects on it.")
    rows = []
    for m in models:
        tm = item_time_per_task(caps, m)
        rows.append([m.id] + [_fmt(tm[i], 1) for i in items])
    _print_table(["config", *short], rows, right=range(1, len(short) + 1))
    _print_text("\n" + _items_legend(short, items))
    return 0


def cmd_sanity(args) -> int:
    """Route every level-only case in sanity.yaml and show what the pool picks.

    Each case is an id, a label and the levels it asks for; it carries no task text and no
    target config. The set is a reading of the current pool and definition, not a test.
    """
    caps, models, services = load_routing()
    spec = load_sanity(sanity_path())
    results = [
        _route_sanity_case(caps, models, services, case, i, args.mode)
        for i, case in enumerate(spec["tasks"], start=1)
    ]
    if args.json:
        print(json.dumps({"mode": args.mode, "results": results}, ensure_ascii=False, indent=2))
        return 0
    rows = [
        [
            r["id"],
            r["label"],
            _levels_str(r["levels"]),
            r["chosen"] or "-",
            r["service"] or "-",
            _fmt(r["cost_per_task"], 4),
            "yes" if r["fallback"] else "",
        ]
        for r in results
    ]
    _print_table(
        ["id", "label", "levels", "chosen", "service", "cost/task", "fallback"],
        rows,
        right=(5,),
        wrap={1: _MIN_FREETEXT_WIDTH, 2: _MIN_FREETEXT_WIDTH},
    )
    chosen_ids = {r["chosen"] for r in results if r["chosen"]}
    relaxed = [r for r in results if r["fallback"]]
    _print_text(f"\nmode={args.mode}: distinct configs chosen: {len(chosen_ids)}; relaxed: {len(relaxed)}")
    for r in relaxed:
        _print_text(f"  {r['id']}: relaxed " + ", ".join(f"{x['item']} {x['from']}->{x['to']}" for x in r["relaxations"]))
    return 0


def cmd_usage(args) -> int:
    """Service failures are part of the snapshot, so they never change the exit code."""
    from . import usage  # imported lazily so the routing commands never load httpx

    snap = usage.snapshot()
    usage.write_cache(os.environ, snap)  # a fresh read is as good as a cached one for route
    if args.json:
        print(json.dumps(snap, ensure_ascii=False, indent=2))
        return 0
    rows = []
    for svc in snap["services"]:
        name = svc["name"] + (f" ({svc['plan']})" if svc.get("plan") else "")
        if svc["status"] != "ok":
            rows.append([name, svc["status"], "-", "-", "-", svc.get("message", "")])
            continue
        for i, w in enumerate(svc["windows"]):
            rows.append([name if i == 0 else "", "ok" if i == 0 else "", w["label"], f"{w['remainingPercent']}%", _local_time(w["resetsAt"]), w.get("detail", "")])
        if svc.get("credits"):
            c = svc["credits"]
            rows.append(["", "", c["label"], f"{c['remaining']:.2f} {c['unit']}", "-", ""])
    _print_table(
        ["service", "status", "window", "remaining", "resets", "detail"],
        rows,
        right=(3,),
        wrap={5: _MIN_FREETEXT_WIDTH},
    )
    _print_text(f"\nfetched at {_local_time(snap['fetchedAt'])}")
    return 0


def cmd_log(args) -> int:
    """Summarize the delegation log by config and service.

    Malformed lines are skipped with a count on stderr; a missing file is zero records. When
    logging is off there is no log to read, so the command is an error rather than an empty one.
    """
    path = delegation_log.log_path()
    if path is None:
        print("error: delegation log is off", file=sys.stderr)
        return 2
    records, skipped = delegation_log.read_records(path)
    if skipped:
        print(f"warning: skipped {skipped} broken line(s) in {path}", file=sys.stderr)
    cutoff = delegation_log.parse_since(args.since) if args.since else None
    summary = delegation_log.summarize(records, cutoff)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    rows = [
        [
            g["chosen"] or "-",
            g["service"] or "-",
            str(g["routes"]),
            str(g["outcomes"]),
            _pct(g["pass_rate"]),
            _num(g["median_duration_s"]),
            _num(g["median_rounds"]),
        ]
        for g in summary["groups"]
    ]
    total = summary["total"]
    rows.append(
        [
            "total",
            "",
            str(total["routes"]),
            str(total["outcomes"]),
            _pct(total["pass_rate"]),
            _num(total["median_duration_s"]),
            _num(total["median_rounds"]),
        ]
    )
    _print_table(
        ["config", "service", "routes", "outcomes", "pass", "duration_s", "rounds"],
        rows,
        right=range(2, 7),
    )
    return 0


def cmd_log_outcome(args) -> int:
    """Append an outcome for a route id (status pass / fail / abandoned)."""
    path = delegation_log.log_path()
    if path is None:
        print("error: delegation log is off", file=sys.stderr)
        return 2
    records, _ = delegation_log.read_records(path)
    route = next(
        (r for r in records if r.get("type") == "route" and r.get("id") == args.id), None
    )
    if route is None:
        print(f"error: unknown delegation id: {args.id}", file=sys.stderr)
        return 2
    now = datetime.now(timezone.utc)
    if args.duration is not None:
        duration_s = args.duration
    else:
        started = delegation_log.parse_ts(route.get("ts"))
        duration_s = round((now - started).total_seconds(), 1) if started else None
    record = delegation_log.outcome_record(
        id=args.id,
        status=args.status,
        duration_s=duration_s,
        rounds=args.rounds,
        implementer=args.implementer,
        note=args.note,
        now=now,
    )
    try:
        delegation_log.append_record(path, record)
    except OSError as e:
        print(f"error: outcome not written: {e}", file=sys.stderr)
        return 2
    return 0


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.0f}%"


def _num(value: float | None) -> str:
    if value is None:
        return "-"
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def _local_time(iso: str | None) -> str:
    if not iso:
        return "-"
    return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M")


def _route_sanity_case(caps, models, services, case, index: int, mode: str) -> dict:
    """Route one sanity case, which carries only `id`, `label` and `levels`.

    Usage and the personal services settings are not read, so the reading depends on the pool
    and definition alone; a config on several services shows the first one pool.yaml lists.
    """
    if not isinstance(case, dict):
        raise ValueError(f"sanity case {index}: each entry must be a mapping, got {type(case).__name__}")
    where = f"sanity case {case['id']!r}" if case.get("id") else f"sanity case {index}"
    for key in ("id", "label", "levels"):
        if not case.get(key):
            raise ValueError(f"{where}: missing or empty {key!r}")
    if not isinstance(case["levels"], dict):
        raise ValueError(f"{where}: 'levels' must be a mapping of item to level")
    try:
        estimator = FixedLevels(caps, case["levels"])
    except ValueError as e:
        raise ValueError(f"{where}: {e}") from None
    # The cases carry no task text and no image, so metadata filtering has no input length to
    # compare against and only the levels decide the assignment.
    decision = route(caps, models, estimator.estimate(""), TaskMeta(), mode=mode, services=services)
    chosen = decision.selection.get("chosen") or {}
    return {
        "id": case["id"],
        "label": case["label"],
        "levels": case["levels"],
        "chosen": decision.chosen.id if decision.chosen else None,
        "service": decision.service,
        "cost_per_task": chosen.get("cost"),
        "time_per_task_s": chosen.get("time_per_task_s"),
        "fallback": decision.fallback,
        "relaxations": [
            {"item": r.item, "from": r.from_level, "to": r.to_level}
            for r in decision.relaxations
        ],
    }


def _levels_str(levels: dict[str, str]) -> str:
    """The case's levels in the table's `initial=first letter` form (`none` left out)."""
    return ",".join(f"{_abbrev(a)}={lv[0]}" for a, lv in levels.items() if lv != "none") or "-"


def _abbrev(item: str) -> str:
    """Initials of the item name, so the tables stay narrow."""
    return "".join(part[0] for part in item.split("_"))


def _fmt(v, nd: int) -> str:
    return "-" if v is None else f"{v:.{nd}f}"


def _is_terminal() -> bool:
    """Whether stdout is a terminal, so the output can be shaped for a terminal instead of a pipe."""
    return sys.stdout.isatty()


def _print_text(text: str) -> None:
    """Print one line of prose. In a terminal it wraps to the terminal width; otherwise it is left as is."""
    if _is_terminal():
        Console(file=sys.stdout).print(Text(text))
    else:
        print(text)


def _print_table(
    header: list[str],
    rows: list[list[str]],
    right: range | tuple[int, ...] = (),
    wrap: Mapping[int, int] | None = None,
) -> None:
    """Print a table, right-aligning `right` and letting only the free-text columns in `wrap` wrap.

    `wrap` maps a free-text column to its minimum display width, so such a column never shrinks to
    a few characters. In a terminal, identifier and numeric columns are never wrapped, truncated,
    or ellipsized; the free-text columns wrap to use the rest of the terminal width, with a
    one-cell gap between columns. A table whose identifiers and numbers plus the free-text minimums
    do not fit may grow past the terminal width. When stdout is not a terminal every record stays
    on one un-wrapped line with no borders or color, so `grep` and `awk` still see the rows.
    """
    wrap = wrap or {}
    if not _is_terminal():
        _print_table_plain(header, rows)
        return
    console = Console(file=sys.stdout)
    # Rich would shrink and crop columns to the terminal width; grow the console past it when the
    # columns that must not wrap plus the free-text minimums cannot fit, so nothing is lost.
    fixed = sum(_natural_width(header, rows, i) for i in range(len(header)) if i not in wrap)
    needed = fixed + len(header) - 1 + sum(wrap.values())
    console.width = max(console.width, needed)
    table = Table(
        box=None,
        show_header=True,
        header_style="bold",
        pad_edge=False,
        padding=(0, 1),
        collapse_padding=True,
    )
    for i, name in enumerate(header):
        table.add_column(
            Text(name),
            justify="right" if i in right else "left",
            no_wrap=i not in wrap,
            overflow="fold",
            min_width=wrap.get(i),
        )
    for row in rows:
        table.add_row(*[Text(str(cell)) for cell in row])
    console.print(table)


def _natural_width(header: list[str], rows: list[list[str]], column: int) -> int:
    """The display width of the widest cell in `column`, header included."""
    return max(cell_len(str(r[column])) for r in [header, *rows])


def _print_table_plain(header: list[str], rows: list[list[str]]) -> None:
    """The pipe/file rendering: two-space columns, no wrapping, no truncation, no terminal codes."""
    widths = [max(len(str(x)) for x in col) for col in zip(header, *rows)] if rows else [len(h) for h in header]

    def line(cells) -> str:
        return "  ".join(str(x) + " " * (w - len(str(x))) for x, w in zip(cells, widths))

    print(line(header))
    print(line(["-" * w for w in widths]))
    for r in rows:
        print(line(r))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "route":
            return cmd_route(args)
        if args.cmd == "models":
            return cmd_models(args)
        if args.cmd == "sanity":
            return cmd_sanity(args)
        if args.cmd == "criteria":
            return cmd_criteria(args)
        if args.cmd == "usage":
            return cmd_usage(args)
        if args.cmd == "log":
            if args.log_cmd == "outcome":
                return cmd_log_outcome(args)
            return cmd_log(args)
    except (RuntimeError, ValueError, KeyError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
