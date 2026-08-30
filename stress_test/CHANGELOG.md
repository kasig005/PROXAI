# PROXAI stress-test work — full changelog

Branch: `ssg-lugia-stress-test` · PR: pasqualeleonardolazzaro/PROXAI#3 ·
Issue: pasqualeleonardolazzaro/PROXAI#2

## Goal

Stress-test PROXAI against **several non-trivial pipelines** and check whether its
provenance graph is *diagnostically useful* — i.e. can it point at the pipeline
stage responsible for a behaviour change automatically, rather than a human
digging stage by stage.

Two pipelines are wired up so far:

| profile | pipeline | why it's a stress test |
|---|---|---|
| `ssg_lugia` | SSG-LUGIA genomic-island prediction | multi-stage numpy signal pipeline, no pandas, known ground truth (one config = one stage changed) |
| `census_ml` | scikit-learn preprocessing + training on the Census/Adult dataset | tabular, deterministic, 5 independently tunable stages |

---

## 1. New — stress-test framework

### `stress_test/` (new directory)

| File | Purpose |
|---|---|
| `ssg_lugia.py` | SSG-LUGIA **profile**: 11 configs + adapter path + `SSG_LUGIA_CONFIG` env var + `[SSG-LUGIA pipeline]` summary line + activity→stage map. |
| `census_ml.py` | Census-ML **profile**: 11 configs (one knob per stage: `impute_strategy`, `encoding`, `scaler`, `k_best`, `classifier`) + mapping. |
| `configs.py` | Back-compat shim — `from ssg_lugia import CONFIGS`. |
| `run_stress_test.py` | `--profile <name>` driver. Per config: robust batched `clear_graph()`, run `prolit_run.py --use_manual_code`, **retry on known-transient LLM failures** (`--retries`, default 2), snapshot the provenance graph to `results/<config>.json` via the Neo4j driver (no APOC). Generic `key=value` metric parsing from the summary line. Writes `results/_summary.json`. |
| `compare.py` | `--profile <name>`. Buckets each graph's activities into the profile's stages by their **code** (deterministic), scores per-stage provenance divergence from baseline (`0.5·column-set change + 0.4·entity-volume change + 0.1·op-count change`), ranks, checks the top stage against the config's known knob. Writes `results/_comparison.{json,md}` + a stdout table. Stdlib only. |
| `demo.py` | `--profile <name>` one-command demo: check Neo4j → run a config subset → compare → print table + use cases + Neo4j queries. |
| `README.md` | How it works, per-profile run commands, and **"Adding another pipeline"** (adapter rules + profile contract, with `census_ml` as the worked example). |
| `ISSUE.md` | The 5 PROXAI robustness bugs found (mirrors issue #2). |
| `CHANGELOG.md` | This file. |
| `ssg-lugia-biopython-compat.patch` | One-line Biopython ≥ 1.78 fix for the SSG-LUGIA submodule (can't be committed through the submodule pointer). |
| `results/` | Generated output — git-ignored. |

### `pipelines/` (new adapters)

- **`ssg_lugia_pipeline.py`** — wraps SSG-LUGIA's `loadGenome → extractFeatures →
  detectAnomalies → post-processing → getGenomicIslands` onto **one** pandas
  DataFrame. Subscribes to the bare per-window frame (`window_index/start/end`)
  **before** feature extraction, so every stage — feature extraction included —
  is a tracked column-add. Resolves `external/SSG-LUGIA/codes` independently of
  `__file__`; loads SSG-LUGIA's `utils.py` by path to dodge the name clash with
  PROXAI's root `utils.py`; reads per-run config from `SSG_LUGIA_CONFIG`.
- **`census_ml_pipeline.py`** — `pd.read_csv` → subscribe → `clean/impute` →
  `encode` → `scale` → `select` → `train` on `datasets/census.csv`. One subscribed
  frame, one column-adding transformation per stage, fully deterministic
  (`random_state`, stratified split kept as an `is_test` column). Prints
  `[census-ml pipeline] n_features=… test_accuracy=… test_f1=…`.

---

## 2. Changed — PROXAI core (one robustness guard)

- **`tracking/column_entity_approach.py`** — `column_entitiy_vision` did
  `current_activities[act-1]` where `act` indexes tracker snapshots and
  `current_activities` comes from the (variable-length, non-deterministic) LLM
  `descript()` output. When the LLM returns fewer activities than there are
  `analyze_changes()` snapshots, this threw `IndexError` and lost the whole run.
  Added a guard to skip snapshots with no matching activity. **Prevents the
  crash; does not fix attribution.** (Issue #2 item 3.)

---

## 3. Changed — environment / compatibility

> These are workarounds to make PROXAI runnable on the dev machine. They should
> become config-driven before merge — none are the contribution.

| File | Change | Why |
|---|---|---|
| `LLM/LLM_formatter.py`, `LLM/LLM_activities_descriptor.py`, `LLM/LLM_activities_used_columns.py` | default `model_name` `llama-3.3-70b-versatile` → `openai/gpt-oss-120b` | the Groq account in use exposes **no Llama models**; every LLM call 404'd. Still `ChatGroq`, still `KEY.py`. |
| `rag_system/config/settings.py` | `LLM_MODEL_NAME` → `os.getenv("LLM_MODEL_NAME", "qwen2.5:7b")`; added `OLLAMA_BASE_URL`; `GROQ_API_KEY` kept, marked unused | move Graph-Chat LLM to local inference |
| `rag_system/llm/generator.py` | Graph-Chat LLM `ChatGroq` → `ChatOllama` (`num_predict`, `base_url`) | same; optional, easy to gate behind a flag |
| `neo4j/docker-compose.yml` | `+NEO4J_server_memory_heap_max__size=6G`, `heap_initial 2G`, `pagecache 2G`, `db.memory.transaction.total.max 8G` | headroom for granularity-3 provenance graphs |
| `.gitignore` | `+stress_test/results/` | generated output |
| `.gitmodules` + `external/SSG-LUGIA` | added SSG-LUGIA as a submodule (pinned `de7cb6b`) | the test-case codebase |
| venv (not in `requirements.txt` yet) | `pip install biopython` | SSG-LUGIA imports `Bio` |

`extracted_code.py` is deliberately **not** committed — it's a per-run scratch
file (`run_stress_test.py` overwrites it with the active profile's adapter).

---

## 4. Results

### `ssg_lugia` — full 11-config sweep, granularity 1

Behaviour deltas are clean and interpretable:

| config | knob | windows | islands | Δislands | Δwindows |
|---|---|--:|--:|--:|--:|
| `baseline_F` | — | 47,991 | 14 | — | — |
| `classifier_R` | SSG-LUGIA-R | 47,991 | 34 | **+20** | 0 |
| `classifier_P` | SSG-LUGIA-P | 47,991 | 10 | −4 | 0 |
| `window_coarse_20000` | w=20k, dw=200 | 23,946 | 5 | −9 | −24,045 |
| `window_fine_5000` | w=5k, dw=50 | 96,081 | 17 | +3 | +48,090 |
| `window_very_fine_1000` | w=1k, dw=10 | 480,804 | 9 | −5 | +432,813 |
| `step_dense_25` | dw=25 | 191,962 | 31 | +17 | +143,971 |
| `feature_karlin_raw` | karlin=raw | 47,991 | 14 | 0 | 0 |
| `feature_karlin_original` | karlin=original | 47,991 | 13 | −1 | 0 |
| `feature_no_entropy` | entropy=off | 47,991 | 12 | −2 | 0 |
| `feature_more_pca` | pca 5/5/5 | 47,991 | 15 | +1 | 0 |

Classifier variant drives the biggest island swing (10↔34) at zero window
change → an anomaly-detection effect. Window/step changes window count 0.5×–10×
→ a scanning-resolution effect. Feature-representation tweaks barely move
anything → smallest effect.

**Stage localisation (granularity 1): 0/9.** Graphs are tens of nodes; the
divergence metric is dominated by run-to-run LLM wording variance. At
granularity 3 the graphs are ~750k nodes but the activity layer is
intermittently lost (issue #2 items 1 + 4) — a single baseline re-run gave 0 vs
17 Activity nodes.

Full baseline provenance graph at granularity 3 (restructured v2 pipeline):
**767,856 Entity · 19 Column · 17 Activity · ~1.5M relationships**.

### `census_ml` — granularity 1

Pipeline verified end to end: `baseline` (104 features, test_accuracy 0.851,
test_f1 0.666) and `impute_constant` (107 / 0.853 / 0.669), `clf_rf`
(104 / 0.846 / 0.663) all produced clean provenance graphs (5 Activity nodes,
one per stage, correctly code-classified).

A full 11-config sweep on Groq was blocked by that account's daily token cap
(200k TPD — exhausted during development). Re-running on the local Ollama
backend (`PROXAI_LLM_BACKEND=ollama`, `qwen2.5:7b`) removes the rate limit but
is ~100 s/`descript()` on CPU, so the full 11-config table is an overnight job.
`descript()` on Ollama parses cleanly for this pipeline (5 activities).

---

## 5. Findings

**Works:** the harness, and the **behaviour-delta comparison** across configs for
both pipelines — clean, interpretable tables (see §4).

**Blocked — automated stage attribution.** Two reasons:

1. **Granularity 1** — provenance graphs are tiny (tens of nodes); the divergence
   metric is dominated by run-to-run variation in the LLM's activity wording, not
   real pipeline changes.
2. **Granularity 3** — richer graphs (~750k nodes), but activity creation is
   intermittently and silently lost: identical re-runs of one SSG-LUGIA config
   gave 0 vs 17 Activity nodes, both reporting `success`. Root cause = issue #2
   items 1 (Neo4j write errors swallowed) + 4 (`descript()` non-determinism,
   reproduced on **both** pipelines).

The `--retries` mechanism (added here) works around item 4 for sweeps but doesn't
fix the underlying non-determinism.

## 6. Next steps

1. Land issue #2 fixes 1 and 4 in PROXAI core (loud failure on Neo4j write
   errors; validated / deterministic activity extraction).
2. Add a 3rd pipeline (NLP or image preprocessing chain) — the harness is
   profile-driven, so this is one adapter + one profile module.
3. Re-run both sweeps at granularity 3 once activity creation is deterministic,
   then evaluate stage-attribution accuracy across all pipelines.

## 7. Commit history (branch `ssg-lugia-stress-test`)

```
08baa26  Compat + env changes to run PROXAI locally for the stress test
da0045c  tracking: guard column_entitiy_vision against activity/snapshot count mismatch
ba69736  Add multi-pipeline stress-test harness + SSG-LUGIA as first test case
4d47d27  stress_test: profile system + second pipeline (census_ml)
a3b234b  stress_test/ISSUE.md: note bug #4 reproduces on the census_ml pipeline
f34ad36  LLM extraction robustness: bound max_tokens + tolerant block parsing
c1fce75  LLM helpers: default to local Ollama; add rate-limit handling for Groq path
(+ this changelog)
```
