# Check routing

[日本語](check-routing.ja.md)

Use your definition, catalog and `pool.yaml` ([register configs](register-configs.md)) to see which configs receive which tasks, and why.

## Steps

1. Write cases you can judge yourself in `sanity.yaml` (omitted items default to `none`).
   ```sh
   echo '{tasks: [{id: q1, label: simple count, levels: {sql: low}}, {id: q2, label: cohorts, levels: {sql: high}}]}' > "${XDG_CONFIG_HOME:-$HOME/.config}/capability-router/sanity.yaml"
   ```
2. Regenerate the criteria, then route every case without usage data. If an assignment looks wrong, revise the anchors, catalog values or thresholds and try again.
   ```sh
   capability-router criteria && capability-router sanity
   ```
3. Route one real set of requirements and inspect the full decision as JSON.
   ```sh
   capability-router route --no-usage --no-log --explain --levels sql=mid "task text"
   ```

<a id="inspect"></a>
## Investigate a surprising choice

Check the relevant part of `--explain` output for your situation.

- `fallback: true`: inspect `relaxations`. No config passed, so requirements were lowered one item at a time. The result may not meet the original requirements.
- A larger config than expected: inspect `selection.traded_up` (a `balanced` trade-up) or `selection.service` ([services with more surplus come first](how-it-works.md#service-first)).
- A config is never selected: inspect its `reasons` in `ranking`. Run `capability-router models --detail` for scores and thresholds.
- Cost has no effect: run `capability-router models --costs`. Equal costs do not distinguish configs. Configs with missing items are excluded in `cheap`/`balanced`.
- Too many or too few trade-ups: adjust the `routing` keys in `capabilities.yaml` ([list](reference.md#capabilities)).
