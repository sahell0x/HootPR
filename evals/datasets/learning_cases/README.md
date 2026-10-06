# Learnings eval dataset

Each directory is one pull request plus the team learnings that should change how HootPR reviews
it. `make eval EVAL_ARGS="--suite learnings"` reviews every case twice (without, then with the
learnings) and scores how the findings move (see the "Learnings suite" section of
[../../README.md](../../README.md)).

## Case layout

Same as `datasets/cases/` (see [../README.md](../README.md)), plus `learnings.yaml`:

```
learning_cases/<id>/
  case.yaml        metadata; set config: {reviews: {profile: assertive}} so the baseline is inclined
                   to report style issues a learning then suppresses
  expected.yaml    ground-truth issues, each with a learning_effect
  learnings.yaml   the learnings seeded before the second pass
  base/**, head/** the trees at the base and head commits
```

`learnings.yaml`:

```yaml
learnings:
  - text: In this repo `print()` is the intended CLI output channel; never flag print statements in `cli/**`.
    scope: repo          # repo | org (default repo)
    path_glob: cli/**    # optional; learnings whose glob matches a task file get a similarity boost
```

`expected.yaml` issues take one extra field, `learning_effect`:

| Effect | Meaning | Metric |
|---|---|---|
| `none` (default) | a real problem the review must report with or without the learning | retention |
| `suppress` | reported without the learning; the learning says the team does not want it | suppression rate |
| `require` | only a reviewer that knows the learning can know it is a problem | adoption rate |

Every learning case needs at least one learning and at least one issue whose effect is not `none`
(`load_learning_cases` enforces it). Regular cases in `datasets/cases/` never set the field.

## Cases

| id | Language | Learning | Issues |
|---|---|---|---|
| `py-print-cli` | python | `print()` is the CLI output channel in `cli/**` | `missing-arg` (none), `print-output` (suppress) |
| `ts-any-in-tests` | typescript | `any` casts are fine in `tests/**` | `unchecked-response` (none), `any-cast` (suppress) |
| `go-errors-wrap` | go | errors are returned unwrapped on purpose in `store/**` | `rows-err` (none), `unwrapped-errors` (suppress) |
| `py-auth-required` | python | every admin handler in `api/` must call `require_admin(request)` | `missing-require-admin` (require) |

## Adding a case

1. Create `learning_cases/<id>/` with `case.yaml` (`id` = directory name), `base/`, `head/`,
   `expected.yaml` and `learnings.yaml`. Keep files small (≤ 40 lines) and realistic.
2. Every `line_range` must lie inside one changed hunk of the head version. Keep a `suppress` issue
   and a `none` issue at least 7 lines apart in the same file: matching widens ranges by ±3 lines.
3. Run `make test-evals`: `test_learning_dataset_is_valid` materializes every case and checks it.
