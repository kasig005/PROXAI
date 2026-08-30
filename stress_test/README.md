# PROXAI stress-test harness

Goal: **stress-test PROXAI against several real, non-trivial pipelines** and check
whether its provenance graph is not just captured but *diagnostically useful* —
i.e. can it point at the pipeline stage responsible for a change in behaviour,
automatically, instead of a human digging stage by stage.

First pipeline under test: **SSG-LUGIA** (genomic-island prediction). It is
deliberately unlike PROXAI's existing tabular demos — a multi-stage numpy signal
pipeline with a known ground truth, because each test config changes exactly one
stage.

---

## Layout

| File | What it is |
|---|---|
| `configs.py` | The 11 SSG-LUGIA test configs. Each changes **one** knob vs. a baseline: classifier variant (F/R/P → anomaly-detection stage), window size/step (→ feature-extraction / scanning stage), feature representation (karlin / entropy / pca → feature-extraction stage). |
| `run_stress_test.py` | Runs `prolit_run.py` once per config (config passed via the `SSG_LUGIA_CONFIG` env var), then snapshots each provenance graph to `results/<config>.json` before the next run wipes Neo4j. |
| `compare.py` | Diffs every config's graph against the baseline: buckets activities into the 4 stages by their code, scores each stage's provenance divergence (0 = identical, 1 = fully changed), and writes a table to `results/_comparison.{json,md}`. |
| `demo.py` | One command: checks Neo4j, runs a subset of configs, runs `compare.py`, prints key figures + use cases + the Neo4j queries to show the graph. |
| `ISSUE.md` | The 5 PROXAI robustness bugs this stress test surfaced (paste into the issue tracker). |
| `results/` | Generated output (git-ignored). |

The pipeline adapter itself lives at `../pipelines/ssg_lugia_pipeline.py`.

---

## Running it

### Setup (once)

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install biopython                      # SSG-LUGIA needs Bio; not in requirements yet
git submodule update --init --recursive    # pulls external/SSG-LUGIA
git -C external/SSG-LUGIA apply ../../stress_test/ssg-lugia-biopython-compat.patch
cd neo4j; docker compose up -d; cd ..
# create KEY.py at the repo root:  MY_KEY = "gsk_...your Groq key..."
```

### One config (sanity)

```powershell
Copy-Item -Force pipelines\ssg_lugia_pipeline.py extracted_code.py
python prolit_run.py `
  --dataset external/SSG-LUGIA/codes/sample_data/NC_003198.1.fasta `
  --pipeline pipelines/ssg_lugia_pipeline.py `
  --frac 1.0 --granularity_level 1 --use_manual_code
```

### Full sweep + comparison

```powershell
python stress_test/run_stress_test.py --dataset external/SSG-LUGIA/codes/sample_data/NC_003198.1.fasta
python stress_test/compare.py
# results/*.json, results/_summary.json, results/_comparison.md
```

`--granularity_level` defaults to **1**. Level 3 ("Full") produces ~750k nodes /
~2.5M relationships **per run** on this genome — only run it for a single config,
not the 11-config sweep. `--only <names>` runs a subset.

### Demo

```powershell
python stress_test/demo.py            # 4 configs @ granularity 1
python stress_test/demo.py --quick    # 2 configs
python stress_test/demo.py --full     # all 11
```

---

## Adding another pipeline (the point of this harness)

To stress-test PROXAI with a second system, you need **an adapter** and **a config
list**. Mirror the SSG-LUGIA setup:

1. **Write `pipelines/<name>_pipeline.py`** exposing `run_pipeline(args, tracker)`.
   Rules learned from SSG-LUGIA:
   - `tracker.subscribe(df)` must happen **before the first stage you want
     tracked**. Anything that runs before `subscribe()` is invisible to PROXAI.
   - Make each stage **one clear DataFrame transformation** (add a column / change
     a column) immediately followed by `tracker.analyze_changes(df)`. The LLM
     activity extractor keys off the code between `analyze_changes` calls.
   - If the target tool works on numpy / tensors, wrap each stage's output as a
     DataFrame (one row per unit — window, record, token…) purely so the tracker
     has something to diff.
   - Read the per-run configuration from an env var (see `_load_config()` in
     `ssg_lugia_pipeline.py`) so the same file can be run many times unchanged.
   - Resolve any external-code paths independently of `__file__` — in
     `--use_manual_code` mode the file is copied to `extracted_code.py` at the
     repo root.

2. **Write `stress_test/<name>_configs.py`** — a baseline plus one entry per
   single-knob change, each mapping to a known stage.

3. **Point the driver at it** — `run_stress_test.py` currently imports
   `configs.CONFIGS` and hard-codes `pipelines/ssg_lugia_pipeline.py`; generalise
   those two (a `--pipeline` / `--configs-module` pair) when the second pipeline
   lands.

4. **Extend `compare.py`'s stage buckets** — `STAGE_CODE_KEYWORDS` maps code
   substrings to stages; add the new pipeline's stage function names.

Candidate second/third pipelines: any multi-stage preprocessing or ML pipeline
with tunable per-stage parameters and a measurable output (a scikit-learn
`Pipeline` with swappable steps, a different bioinformatics tool, an NLP
preprocessing chain).

---

## Repo changes made for this work

### Stress-test framework (new, all in `stress_test/` + `pipelines/`)
- `pipelines/ssg_lugia_pipeline.py` — SSG-LUGIA adapter. **v2**: subscribes to a
  bare per-window frame *before* feature extraction, so every stage (feature
  extraction included) is a tracked column-add. v1 subscribed after feature
  extraction, which made the feature-representation configs invisible.
- `stress_test/{configs,run_stress_test,compare,demo}.py` — as above.
- `.gitignore` — added `stress_test/results/`.
- `external/SSG-LUGIA` — added as a submodule (pinned at `de7cb6b`). It needs a
  one-line Biopython ≥ 1.78 compat fix (`codes/feature_extraction.py`: drop the
  `Bio.Alphabet` import and the alphabet arg to `Seq()`), kept as
  `stress_test/ssg-lugia-biopython-compat.patch` because it can't be committed
  through the submodule pointer. After `git submodule update --init`:

  ```
  git -C external/SSG-LUGIA apply ../../stress_test/ssg-lugia-biopython-compat.patch
  ```

  Should be upstreamed to SSG-LUGIA.

### PROXAI core (one robustness patch)
- `tracking/column_entity_approach.py` — guard so `column_entitiy_vision`
  skips a snapshot with no matching activity instead of `IndexError`
  (see `ISSUE.md` #3). This prevents the crash; it does not fix attribution.

### Environment / compatibility (needed to run at all — should be config-driven before merge)
- `LLM/LLM_formatter.py`, `LLM/LLM_activities_descriptor.py`,
  `LLM/LLM_activities_used_columns.py` — default `model_name`
  `"llama-3.3-70b-versatile"` → `"openai/gpt-oss-120b"`. The Groq account in use
  has no Llama models; every LLM call 404'd. Still `ChatGroq`, still `KEY.py`.
- `rag_system/config/settings.py` — `LLM_MODEL_NAME` → env-overridable
  `"qwen2.5:7b"`; added `OLLAMA_BASE_URL`; `GROQ_API_KEY` kept but unused.
- `rag_system/llm/generator.py` — Graph-Chat LLM `ChatGroq` → `ChatOllama`
  (local inference; optional, easy to gate behind a flag).
- `neo4j/docker-compose.yml` — heap 6 G / pagecache 2 G / `db.memory.transaction.total.max` 8 G,
  headroom for granularity-3 graphs.
- venv — added `biopython` (SSG-LUGIA dependency, not yet in `requirements.txt`).

---

## Findings so far

### Works: behaviour-delta comparison (granularity 1, all 11 configs)

| config | knob changed | windows | islands | Δislands | Δwindows |
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

Reads cleanly: classifier variant drives the biggest island swing (10↔34) at zero
window change → an anomaly-detection effect; window/step changes window count
0.5×–10× → a scanning-resolution effect; feature-representation tweaks barely
move anything (±2 islands, 0 window change) → smallest effect.

### Blocked: automated stage attribution

- **Granularity 1** — provenance graphs are 25–43 nodes; the divergence metric is
  dominated by run-to-run variation in the LLM's activity wording, not by real
  pipeline changes. 0/9 correct stage picks.
- **Granularity 3** — richer graphs (~750k nodes), but activity creation is
  intermittently and silently lost: identical re-runs of one config gave 0 vs 17
  Activity nodes, both reporting `success`. See `ISSUE.md` #1 and #4.

Bottom line: the harness and the behaviour-delta comparison are usable now.
Provenance-based stage attribution needs the PROXAI-core fixes in `ISSUE.md`
(deterministic activity extraction; not swallowing Neo4j write errors) before a
multi-config, multi-pipeline sweep can be trusted.

## Next steps

1. Land `ISSUE.md` fixes #1 and #4 in PROXAI core.
2. Add pipeline #2 (see "Adding another pipeline") and generalise
   `run_stress_test.py` to take `--pipeline` + `--configs-module`.
3. Re-run the SSG-LUGIA sweep at granularity 3 once activity creation is
   deterministic; then evaluate stage-attribution accuracy across both pipelines.
