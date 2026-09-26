# Tutorial: define your own capability items

[日本語](tutorial.ja.md)

capability-router ships no capability items. This tutorial builds one from scratch, using the fictional `examples/` set as a worked shape. It is a procedure, not a script: run the commands yourself and edit the YAML by hand.

The `examples/` definition, catalog, anchors and thresholds were written in exactly the shape below. Their values are made up, not measured.

## The idea: a level is its anchor problems

A **level** is defined by the anchor problems you can solve at that level. The `levels` text in `capabilities.yaml` is a short summary of its anchors. A task's requirement is judged by how close the task is to the level's anchors, and a config satisfies a level when it passes a large enough share of them.

A level with no `examples` is judged from the text alone. That is allowed, but the threshold is then a placeholder, not a measurement. Prefer anchors where you can.

## Flow A: anchors to `level`

### 1. Pick one item

Start with one capability that matters to you and that a text description alone reads ambiguously. Name it after what it measures, not after a model or a tool.

### 2. Write about four anchor problems per level, and tag them

Write about four small problems per level, about twelve for the item, and tag each one `low`, `mid`, or `high`:

- `low`: one obvious step; the answer is easy to check.
- `mid`: several steps, or one step that needs care; still checkable.
- `high`: the hard end for this item; getting it right is itself the deliverable.

Keep them short summaries you can store in YAML. Four per level make the pass rates land on steps of 0.25.

### 3. Write the level text and `examples`

Put the summaries under the item's `examples`, and write the `levels` text as a summary of each group. For example:

```yaml
items:
  coding:
    measures: Implementing a given specification or algorithm as correct code.
    excludes: The finish of a written deliverable.
    levels:
      none: No code is written.
      low: A few obvious lines of change.
      mid: A function or module implemented to specification and checked with tests.
      high: Numerical or complex algorithms implemented down to the specification details.
    examples:
      low:
        - Fix an off-by-one error in an existing loop.
        - Add a missing default value to a function argument.
        - Handle an empty input list without raising.
        - Rename a symbol consistently across one file.
      mid:
        - Implement a config loader with validation and tests.
        - Add a paginated API client method with retry handling.
        - Cache a computed result keyed on the input arguments.
        - Parse a small CSV file into typed records with error reporting.
      high:
        - Implement a numerically stable matrix decomposition from its specification.
        - Implement a parser for a small grammar with error recovery.
        - Implement a diff algorithm with correct hunk boundaries.
        - Implement a concurrent worker pool with backpressure.
```

Run `capability-router criteria` afterwards, and read `criteria.md` to check that the text and the anchors say what you mean.

### 4. Run every config on every anchor and record the pass rates

Have each config solve the anchor problems, and record the share it solved at each level in a file shaped like `examples/anchor-results.yaml`:

```yaml
example-large:
  coding: {low: 1.0, mid: 0.75, high: 0.5}
example-mid:
  coding: {low: 1.0, mid: 0.5, high: 0.25}
```

### 5. Write the catalog `level`

Run the helper, or apply the rule by hand:

```sh
python examples/levels_from_anchors.py anchor-results.yaml --pass-rate 0.5
```

The rule: from `low` upward, take the highest level whose pass rate is at least `--pass-rate` and whose lower levels are too. If `low` is below the pass rate, the config does not even clear `low`, so its level is `-`. The script prints the lines to paste under the config's `items`:

```yaml
items:
  coding: {level: H}
```

A config that clears nothing gets `-`. In block style, quote it as `'-'`, because an unquoted dash starts a YAML sequence and fails to parse:

```yaml
items:
  coding:
    level: '-'
```

### 6. Record cost and time by hand

Give every item a `cost_per_task` and a `time_per_task_s`. The units are yours. If you cannot measure them, put the same value on every config: equal values make the comparison effectively inert without disabling it, and you can fill in real numbers later.

## Flow B: scores and thresholds

When you can measure a pass rate as a number, write the item as a `score` instead of a `level`.

1. Run every config over the whole problem set and take the share it solved, in 0..1. That is the catalog `score`.
2. Put a `thresholds` block on the item in the definition. Set it by hand, or use the placeholder rule in `examples/thresholds.py`:

   ```sh
   python examples/thresholds.py models/ capabilities.yaml --tasks coding=10,long_context=10
   ```

   The script takes the best `score` in the catalog for each item and proposes `low = best / 3`, `high = best - 2 × SE` (or `best × 0.9` when the number of problems is unknown), and `mid` halfway. With only about ten problems the standard error is large, so `high` lands near `low`. Treat the result as a placeholder.

3. A required `score` item passes when the config's score is at least the threshold. A `level` item with `thresholds` maps `H`/`M`/`L` onto the `high`/`mid`/`low` values; without `thresholds` it uses the fixed `1.0` / `2/3` / `1/3`.

## Using a public benchmark

You can build anchors from a public benchmark without naming it in your definition.

- If the benchmark publishes a difficulty split (for example `easy` / `medium` / `hard`), treat each split as one anchor group and follow Flow A: tag a sample of each split as `low` / `mid` / `high`, record per-split pass rates, and write the catalog `level`.
- If it publishes only an overall accuracy, use the accuracy as the `score` and follow Flow B. Without a difficulty split there is no anchor, so the threshold is a placeholder; the pool-relative rule in `examples/thresholds.py` is the starting point.

Write the item's `measures` and `excludes` in capability terms, not benchmark terms. The benchmark is a measurement instrument, not the definition.

## Check the result with sanity

Whichever flow you use, confirm that the level text matches the thresholds and the catalog with `capability-router sanity`. Write a handful of cases in `sanity.yaml` that you can judge by eye, route them, and check that the assignments and the fallbacks read the way you expect. Adjust the anchors, the level text, or the thresholds until they do. The sanity set is a reading, not a pass/fail test.

## Keep the criteria current

Run `capability-router criteria` after every change to `capabilities.yaml`. It writes `criteria.md` beside the definition. `route` warns once when that file no longer matches the definition. It only warns, so regenerate `criteria.md` when you see the warning, before the next estimate.
