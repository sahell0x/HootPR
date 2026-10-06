# HootPR evals

The eval suite (spec §14) measures how good HootPR's reviews are. It runs the **production review
engine** (`app.review.engine.run_engine`) in-process against a dataset of small pull requests with
known ground truth, using `LocalPlatform` and an in-memory trace — nothing is posted anywhere — and
scores the findings.

## Running

```bash
make eval                                              # default models from .env (needs LLM keys)
make eval MODEL_REVIEW=gpt-6-luna MODEL_CHEAP=gpt-5-nano   # override the review / cheap models
make eval EVAL_ARGS="--fake-llm"                       # oracle fake LLM: no keys, pipeline check only
make eval EVAL_ARGS="--cases py-sql-injection,go-map-race"
make eval EVAL_ARGS="--ablations judge_off,tools_off,steps_0,steps_4,steps_8"
make eval EVAL_ARGS="--sandbox docker"                 # docker | local | auto (default)
make eval EVAL_ARGS="--no-llm-match"                   # match on path + lines only
make eval EVAL_ARGS="--suite learnings --fake-llm"   # learnings suite (see below)
make test-evals                                        # the suite's own tests (fake LLM, no network)
```

`--sandbox auto` uses the `hootpr/sandbox` image when it exists (build it with `make sandbox-image`)
and otherwise falls back to a local temp-dir sandbox without the static tools; the report says so.

Every run writes `reports/<date>-<review model>[-fake].md` and `.json`, and updates the tables
below. **Markdown reports are committed; JSON reports are gitignored** (they hold every finding and
are large).

**Fake-LLM runs only verify the pipeline.** The oracle fake answers from `expected.yaml`, so it
scores ~100% by construction; it proves the dataset, engine, matching and reporting work end to end,
not that the reviewer is any good. Only real-LLM runs produce quality numbers.

## Dataset

`datasets/cases/<id>/` — one directory per PR: `case.yaml`, `expected.yaml`, `base/**`, `head/**`.
See [datasets/README.md](datasets/README.md) for the format, the three sources (injected bugs,
reversed CVE fixes, clean PRs) and how to add cases. v1 has 14 cases across Python, TypeScript and Go,
including 3 clean PRs and 2 reversed CVEs.

## Matching

A finding **matches** an expected issue when all of these hold:

1. same file path;
2. the finding's line span overlaps the issue's `line_range` widened by **±3 lines**;
3. an **LLM matcher** (the `cheap` role, strict JSON `{same_issue, reason}`) agrees both describe the
   same defect. Unparseable matcher output counts as "not the same". `--no-llm-match` and fake-LLM
   runs skip this step.

Matching is greedy and one-to-one, most confident finding first: a second finding on an issue that
is already matched is a duplicate and counts as a false positive.

## Metrics

| Metric | Definition |
|---|---|
| Precision | TP / (TP + FP) over all cases (all posted findings, inline and "additional") |
| Recall | TP / (TP + FN); issues of a case that errored count as missed |
| F1 | harmonic mean of precision and recall |
| Per category | recall by the expected issue's category; precision by the finding's category |
| Clean-PR FP rate | share of clean PRs with at least one finding (plus mean findings per clean PR in JSON) |
| Comments/PR | inline comments per PR |
| Tokens in/out per PR, Cost/PR | from the LLM usage of the review (matcher calls excluded) |
| Latency | wall-clock seconds per review (mean and p50) |
| Errors | cases whose review raised (provider down, sandbox failure, ...) |

Ablations (`--ablations`) rerun the whole suite with a stage disabled or the agent step budget
changed, and are reported side by side.

## Learnings suite

`--suite learnings` measures whether a **learning taught in chat measurably changes the next
review** (phase 3). Each case in `datasets/learning_cases/` (format:
[datasets/learning_cases/README.md](datasets/learning_cases/README.md)) is reviewed twice by the
production engine: once without knowledge (baseline) and once with an in-memory knowledge base
(`app.knowledge.memory.InMemoryKnowledge`) seeded from the case's `learnings.yaml`, so the engine
retrieves the learnings by embedding similarity and injects them as a `<team_learnings>` block,
exactly as production does with the `learnings` table.

```bash
make eval EVAL_ARGS="--suite learnings"             # real models (needs review, cheap and embed keys)
make eval EVAL_ARGS="--suite learnings --fake-llm"  # oracle fake LLM + hashing embedder: pipeline check
make eval EVAL_ARGS="--suite learnings --cases py-print-cli"
```

| Metric | Definition |
|---|---|
| Suppression rate | `suppress` issues found in the baseline and **not** found with learnings ÷ `suppress` issues found in the baseline |
| Adoption rate | `require` issues missed in the baseline and found with learnings ÷ `require` issues missed in the baseline |
| Retention | recall of `none` issues with learnings ÷ recall without (a learning must not cost real bugs; n/a when the baseline found none) |
| Retrieval hit rate | share of cases whose second pass injected at least one learning (`EngineResult.learnings_used`) |
| Findings delta | Σ (findings with learnings − findings without) |

Reports go to `reports/<date>-<review model>[-fake]-learnings.md` / `.json`; the table below shows
the latest run. `--ablations` is ignored by this suite. Real runs use the production similarity
threshold (`LEARNINGS_MIN_SIMILARITY`, 0.25) and the `embed` role; **fake runs score 100% by
construction**: the oracle reports `suppress` issues only when the prompt has no `<team_learnings>`
block and `require` issues only when it has one, and retrieval is not thresholded (the hashing
embedder's cosine between a one-line learning and a long task prompt is far below real-model
similarities), so a fake run proves the plumbing (dataset → knowledge → retrieval → prompt → metrics),
not retrieval or model quality.

<!-- learnings:start -->
No learnings run yet: `make eval EVAL_ARGS="--suite learnings"`.
<!-- learnings:end -->

## Latest results

<!-- hootpr:eval-latest:start -->
Latest: [2026-10-04-gpt-6-luna-fake.md](reports/2026-10-04-gpt-6-luna-fake.md) — fake LLM pipeline check

| Review model | Cheap model | Precision | Recall | F1 | Clean-PR FP rate | Cost/PR |
|---|---|---:|---:|---:|---:|---:|
| gpt-6-luna | gpt-5-nano | 100.0% | 100.0% | 100.0% | 0.0% | $0.0005 |
<!-- hootpr:eval-latest:end -->

## History

<!-- hootpr:eval-history:start -->
- [2026-10-04-gpt-6-luna-fake.md](reports/2026-10-04-gpt-6-luna-fake.md): P 100.0%, R 100.0%, F1 100.0%
<!-- hootpr:eval-history:end -->
