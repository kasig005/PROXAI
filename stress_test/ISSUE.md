# Provenance capture silently drops activities / stacks runs — 5 robustness issues found stress-testing PROXAI with a non-tabular pipeline

## Context

While building a stress-test harness for PROXAI (varying one pipeline parameter
at a time and diffing the resulting provenance graphs), I ran PROXAI against
**SSG-LUGIA** — a genomic-island prediction pipeline: `windowing → feature
extraction → anomaly detection → post-processing`, numpy arrays at every stage,
no pandas. Adapter at `pipelines/ssg_lugia_pipeline.py`, harness in `stress_test/`.

PROXAI runs it end to end and the per-run behaviour deltas are clean. But
automated *stage attribution* — "which stage's provenance changed most" — is not
reliably obtainable, because of the issues below. They are ordered by how much
they block that goal.

Environment: Windows 11, Python 3.11, Neo4j 5.7 (community, docker-compose in
`neo4j/`), `granularity_level` 1 and 3 tested.

---

## 1. Neo4j write errors are swallowed → corrupt graphs report success

`graph/neo4j.py` `Neo4jQueryExecutor.query()` catches **every** exception,
prints `[NEO4J ERROR] …`, and returns `None`. Callers in `prolit_run.py` don't
check the return value, so the run continues and exits `0`.

Observed: two identical runs of the same config (`baseline_F`, granularity 3):

| run | Activity nodes | returncode | `success` |
|-----|---------------:|-----------:|:---------:|
| A   | **0**          | 0          | true      |
| B   | 17             | 0          | true      |

In run A, `add_activities()` raised inside `query()` (a malformed activity dict —
see #4), was swallowed, and the run produced a 247k-node graph with **no
Activity nodes and no activity relationships** (`Entity` + `Column` + `BELONGS_TO`
only). Nothing downstream could tell this graph apart from a good one.

**Suggested fix:** let `query()` re-raise (or return a status the caller checks)
for write queries; fail the run loudly when activity/relation creation fails.

## 2. `neo4j.delete_all()` is unbatched → OOMs and fails silently on large graphs

`delete_all()` issues a single `MATCH (n) DETACH DELETE n`. On a granularity-3
graph (~750k nodes / ~2.5M rels for one genome) this exceeds
`db.memory.transaction.total.max` (`MemoryPoolOutOfMemoryError`), the delete
fails, and — via #1 — the run continues and **builds the next run's provenance on
top of the previous graph** (Activity/Column counts accumulate across runs).

**Suggested fix:** batch it (`apoc.periodic.iterate` or a bounded
`… WITH n LIMIT 10000 DETACH DELETE n` loop), and verify the graph is empty
before proceeding.

## 3. `column_entitiy_vision` → `IndexError` when LLM activity count ≠ snapshot count

`tracking/column_entity_approach.py`:

```python
for act in changes.keys():
    if act == 0: continue
    activity = current_activities[act - 1]   # IndexError
```

`current_activities` comes from `descript()`'s LLM output (variable length);
`changes` comes from the number of `tracker.analyze_changes()` calls. When the
LLM returns fewer activities than there are snapshots, the whole run dies here.

Worked around locally with a guard:

```python
if act - 1 >= len(current_activities):
    print(f"[column_entitiy_vision] no activity for snapshot {act} … skipping")
    continue
```

**Suggested fix:** decide the intended alignment (1 activity per
`analyze_changes`?) and either enforce it or handle the mismatch deliberately —
the guard above just prevents the crash, it doesn't fix attribution.

## 4. `descript()` is non-deterministic and its bad outputs aren't validated

`LLM/LLM_activities_descriptor.descript()`:

```python
extracted_text = re.search(r"```(.*?)```", response, re.DOTALL)
if extracted_text:
    return extracted_text.group(1).replace("python\n", "").strip()
# implicit: return None
```

- No fenced block in the response → returns `None` → `prolit_run.py` line 66
  `activities_description.replace(...)` → `AttributeError`, run dies.
  (Hit intermittently on `feature_no_entropy` at granularity 2.)
- A parseable-but-odd dict (e.g. an activity whose `code`/`context` value is not
  a flat primitive) → `ast.literal_eval` succeeds → `add_activities()` throws on
  `SET a = row` → swallowed by #1 → 0-activity graph.

Same pipeline file, run to run, yields 3–17 activities. For a comparison across
N configs this means the activity layer is present for some configs and absent
for others, with no signal that anything went wrong.

Reproduced on a second, unrelated pipeline: a scikit-learn
clean→encode→scale→select→train pipeline on the Census dataset (`census_ml`
stress-test profile). In one 4-config sweep, `baseline` and `clf_rf` succeeded
while `encode_ordinal` and `select_k5` died with the exact
`prolit_run.py:66 AttributeError: 'NoneType' object has no attribute 'replace'`.
So this is not SSG-LUGIA-specific — any pipeline run through `prolit_run.py`
inherits it.

**Suggested fix:** validate `descript()` output (non-empty dict, every value a
`(str, str)` tuple), raise on failure, and consider a deterministic /
schema-constrained extraction (or a retry with a stricter prompt).

## 5. A stage is only observable if it runs *after* `tracker.subscribe()`

Not a bug, but a sharp constraint for adapter authors. My first adapter did:

```python
X = extractFeatures(genome, model)          # feature extraction
df = pd.DataFrame(X, …)
df = tracker.subscribe(df)                   # tracking starts here
tracker.analyze_changes(df)
```

`descript()`'s prompt also says "consider just the code after `df.subscribe()`".
Result: every config that changed feature-representation parameters changed
something PROXAI structurally could not see — its stage-divergence score was a
constant `0.0`. Fixed by subscribing to a bare per-window frame *before* feature
extraction and making every stage (feature extraction included) a tracked
column-adding transformation.

**Suggested fix (docs):** state this explicitly in the "writing a pipeline"
guidance — the subscribed DataFrame must exist before the first stage you want
tracked.

---

## What does work

- PROXAI runs the pipeline end to end at granularity 1, 2, and 3.
- Per-run behaviour outputs (`windows`, `islands_found`) are stable and
  interpretable across all 11 configs.
- With the #5 restructure, feature extraction is now a visible stage
  (divergence score `0.0` → `0.4–0.5` at granularity 1).

## Net effect on the stress test

Behaviour-delta comparison across configs: **works.**
Provenance-based stage attribution: **blocked** — it needs deterministic activity
extraction (#4) and loud failure on write errors (#1) before results across a
multi-config sweep can be trusted.

Repro harness, adapter, and comparison script: `stress_test/` on the branch.
