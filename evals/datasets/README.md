# HootPR eval dataset

Each directory under `cases/` is one pull request with known ground truth. The suite (spec §14)
turns every case into a real two-commit git repository, reviews it with the production engine and
scores the findings against `expected.yaml`.

## Case layout

```
cases/<id>/
  case.yaml        metadata (id must equal the directory name)
  expected.yaml    ground-truth issues (empty list for clean PRs)
  base/**          the full tree at the base commit
  head/**          files the PR adds or changes, overlaid on base/
```

`case.yaml`:

```yaml
id: py-sql-injection          # = directory name
language: python              # python | typescript | go
kind: injected                # injected | cve_reversed | clean
title: Add user lookup by name  # used as the PR title and head commit message
description: Adds find_by_name() so the admin page can search users.  # PR body
source: hand-written          # for cve_reversed: name the CVE, e.g. "CVE-2007-4559 (...), check removed"
deleted: []                   # optional: paths (relative to the repo root) the PR removes
config: {}                    # optional: .hootpr.yaml overrides for this case
```

`expected.yaml`:

```yaml
issues:
  - id: sqli                  # unique within the case
    path: app/users.py
    line_range: [9, 10]       # 1-based line numbers in the HEAD version of the file
    category: security        # bug | security | performance | maintainability | style | docs | test
    severity: critical        # critical | major | minor | nitpick
    description: User-controlled name is interpolated into the SQL string (SQL injection); use a parameterized query.
```

The materializer (`hootpr_evals.case.materialize`) copies `base/`, commits, overlays `head/`,
removes `deleted`, commits again. Author, committer and dates are fixed, so the SHAs are stable.

## Sources

- **injected** — a realistic change with a bug planted in it (SQL injection, missing authorization,
  off-by-one, async `forEach`, unchecked errors, data races, N+1 queries, ...).
- **cve_reversed** — a known vulnerability fix applied in reverse: `base/` has the fix, the PR
  removes it. `source` must name the CVE (the dataset test enforces `CVE-` in it).
- **clean** — a correct PR (refactor, docs, constant extraction). It must list no issues; any
  finding on it counts as a false positive and feeds the clean-PR false-positive rate.

## Rules

- **Anchoring:** every issue's `line_range` must lie inside a single changed hunk on the new side of
  the diff (added or context lines of one hunk). HootPR can only comment on changed hunks, so an
  issue outside them could never be found. `tests/test_dataset.py` enforces it — when the validator
  complains, fix `expected.yaml`, never the validator.
- Line numbers are 1-based and refer to the **head** file.
- Secrets must be obviously fake (e.g. `hootpr-eval-<hex>`), never in a real provider's token format,
  so secret scanners and push protection don't treat the dataset as a leak.
- Keep cases small (one or a few files): the point is to measure the reviewer, not to stress the
  sandbox.

## Growing the dataset (target 40–60 cases)

Add a directory under `cases/` — nothing else is registered anywhere. Then run

```bash
cd evals && uv run --project ../backend pytest -q tests/test_dataset.py
```

to validate the new case (it materializes every case and checks the anchors). Aim to keep the mix
balanced across languages and categories and keep at least one clean case per language.

## v1 cases

| Case | Lang | Kind | Expected issue(s) |
|---|---|---|---|
| `py-sql-injection` | python | injected | security/critical — f-string SQL |
| `py-missing-auth` | python | injected | security/major — admin route without `require_admin` |
| `py-off-by-one` | python | injected | bug/major — page returns `size + 1` items |
| `py-tarfile-traversal` | python | cve_reversed (CVE-2007-4559) | security/critical — tar slip |
| `py-clean-refactor` | python | clean | — |
| `ts-leaked-secret` | typescript | injected | security/critical — hard-coded token |
| `ts-async-foreach` | typescript | injected | bug/major — `forEach(async ...)` |
| `ts-xss` | typescript | injected | security/major — `innerHTML` with user text |
| `ts-prototype-pollution` | typescript | cve_reversed (CVE-2019-10744) | security/critical — `__proto__` guard removed |
| `ts-clean` | typescript | clean | — |
| `go-unchecked-error` | go | injected | bug/major ×2 — ignored `ReadFile`/`Unmarshal` errors |
| `go-map-race` | go | injected | bug/critical — map writes without the mutex |
| `go-n-plus-one` | go | injected | performance/major — one query per order |
| `go-clean` | go | clean | — |
