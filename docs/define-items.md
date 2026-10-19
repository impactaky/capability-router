# Define capability items

[日本語](define-items.ja.md)

Write items in `capabilities.yaml` to estimate task requirements and measure config capabilities ([why](how-it-works.md#items), [installation](start.md)).

## Steps

1. Copy the item definition template to the default location.
   ```sh
   d="${XDG_CONFIG_HOME:-$HOME/.config}/capability-router"; mkdir -p "$d" && cp examples/capabilities.template.yaml "$d/capabilities.yaml"
   ```
2. Replace `my_item` with your own item and add about four anchor problems per level (avoid model or benchmark names in item names). This example defines a SQL item.
   ```yaml
   sql:
     measures: Writing correct SQL queries for a given schema.
     excludes: Database administration and tuning.
     levels: {none: No SQL is written., low: A single-table filter., mid: Joins and aggregation., high: Window functions that must be exactly right.}
     examples: {low: [Count rows in a date range.], mid: [Monthly revenue per customer.], high: [Retention cohorts.]}
   ```
3. Generate and open the criteria. If a task seems to fit two levels, revise the anchors to make the distinction clear (rerun after each edit).
   ```sh
   less "$(capability-router criteria)"
   ```

## Choose how to define values

- To route only to configs you trust with prose (proposals, reports): define a prose item and write a `level` by hand in each catalog file (`'-'` for configs you would not use).
- To use a public benchmark: use problems grouped by difficulty as anchors for each level; use `score` if only overall accuracy is available ([set item values](register-configs.md#values)).
