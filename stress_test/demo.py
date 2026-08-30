"""
One-command demo of the PROXAI x SSG-LUGIA stress test.

What it does:
  1. checks Neo4j is reachable
  2. runs a small set of stress-test configs (baseline + a classifier change +
     two feature-extraction changes) through PROXAI
  3. runs the baseline-vs-config comparison
  4. prints KEY FIGURES, USE CASES, and the Neo4j queries to show the graph

Run from the PROXAI repo root, venv active, Neo4j up:

    python stress_test/demo.py              # 4 configs, granularity 1  (~8 min)
    python stress_test/demo.py --quick      # 2 configs                 (~4 min)
    python stress_test/demo.py --full       # all 11 configs
    python stress_test/demo.py --analyze-only   # skip runs, just re-analyse results/

Needs KEY.py with a working Groq key (see README).
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
RESULTS_DIR = Path(__file__).parent / "results"
DATASET = "external/SSG-LUGIA/codes/sample_data/NC_003198.1.fasta"

DEMO_CONFIGS = ["baseline_F", "classifier_R", "feature_no_entropy", "window_very_fine_1000"]
QUICK_CONFIGS = ["baseline_F", "classifier_R"]

# Measured on a single full-granularity baseline run (granularity_level 3,
# frac 1.0, genome NC_003198.1, ~4.9 MB). The demo itself runs at granularity 1
# to stay fast; these are the "how thorough does it get" numbers to quote.
REFERENCE_FIGURES = """\
  Input genome              NC_003198.1  (~4.9 MB FASTA)
  Windows analysed          47,991
  Genomic islands (F)       14
  Pipeline stages tracked   4  (feature extraction -> anomaly detection ->
                                post-processing -> islands)
  Activities auto-extracted 13  (LLM breaks the 4 stages into 13 operations)
  Provenance graph @ gran 3 767,915 nodes  /  2,495,664 relationships
    - Entity   767,884   (one per tracked feature value / window cell)
    - Column        18
    - Activity      13
  Edge types               BELONGS_TO 767,884 | USED(act->entity) 767,856 |
                           WAS_INVALIDATED_BY 767,856 | WAS_GENERATED_BY 191,992 |
                           USED(act->column) 42 | NEXT 12
  Stress configs           11  (one pipeline knob changed per config)
  LLM calls / run          ~3  (model openai/gpt-oss-120b via Groq)"""

USE_CASES = """\
  1. STAGE ATTRIBUTION / ROOT CAUSE
     "The output changed - which stage caused it?"  compare.py ranks every stage
     by how far its provenance diverged from baseline; the top one is the
     suspect. No manual per-stage diffing.

  2. CHANGE-PROPAGATION TRACING
     A feature-extraction tweak shows up as large divergence in feature
     extraction AND smaller, secondary divergence downstream (anomaly detection,
     post-processing). The graph shows the ripple, not just the origin.

  3. REPRODUCIBILITY / AUDIT
     Every window's feature values and the operations that produced or
     invalidated them are recorded. You can point at the exact operation that
     last wrote `anomaly_score` for window N.

  4. REGRESSION TRIAGE ACROSS A SWEEP
     Instead of eyeballing 11 runs, get one table: config -> knob -> stage
     PROXAI blames -> actual behaviour delta (islands found, windows).

  5. PIPELINE DOCUMENTATION FROM WHAT RAN
     The 13 auto-extracted activities describe what the pipeline actually did,
     independent of code comments.

  6. PROVENANCE-COST PROFILING
     Node/edge counts per granularity level quantify the tracking overhead
     (2.5 M edges for one genome at "Full") - tells you what granularity is
     practical for a batch sweep."""

NEO4J_QUERIES = """\
  Open http://localhost:7474  (Connect URL bolt://localhost:7687, neo4j / adminadmin)
  Paste each, press Ctrl+Enter:

  -- whole pipeline shape: stages and the columns they touch
  MATCH p = (c:Column)-[r]-(a:Activity) RETURN p

  -- the stages, as a graph
  MATCH (a:Activity) RETURN a

  -- stage names + what each does
  MATCH (a:Activity) RETURN a.function_name, a.context

  -- execution order
  MATCH p = (:Activity)-[:NEXT]->(:Activity) RETURN p

  -- sample of data lineage (limited - can be 100k+s of entities)
  MATCH p = (e:Entity)-[:WAS_GENERATED_BY]->(a:Activity) RETURN p LIMIT 100

  -- size of the captured provenance
  MATCH (n) RETURN labels(n)[0] AS type, count(*) AS count ORDER BY count DESC"""


def hr(title=""):
    line = "=" * 78
    return f"\n{line}\n{title}\n{line}" if title else f"\n{line}"


def check_neo4j():
    try:
        from neo4j import GraphDatabase
    except ImportError:
        sys.exit("neo4j driver not installed -- pip install -r requirements.txt")
    try:
        d = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "adminadmin"))
        d.verify_connectivity()
        d.close()
    except Exception as e:  # noqa: BLE001
        sys.exit(f"Neo4j not reachable at bolt://localhost:7687 ({e}).\n"
                 f"Start it:  cd neo4j && docker compose up -d")
    print("Neo4j: reachable")


def run(cmd):
    print(f"\n$ {' '.join(cmd)}")
    r = subprocess.run(cmd, cwd=REPO_ROOT)
    if r.returncode != 0:
        sys.exit(f"command failed ({r.returncode}): {' '.join(cmd)}")


def print_figures():
    print(hr("KEY FIGURES  (reference: single baseline run, granularity 3)"))
    print(REFERENCE_FIGURES)

    summ = RESULTS_DIR / "_summary.json"
    comp = RESULTS_DIR / "_comparison.json"
    if summ.exists():
        data = json.loads(summ.read_text(encoding="utf-8"))
        print(hr("THIS RUN"))
        for s in data:
            ok = "ok  " if s["success"] else "FAIL"
            print(f"  [{ok}] {s['name']:<22} windows={s['windows']} "
                  f"islands_found={s['islands_found']}")
    if comp.exists():
        c = json.loads(comp.read_text(encoding="utf-8"))
        h = c["headline"]
        print(hr("STAGE-LOCALISATION RESULT"))
        print(f"  baseline           : {h['baseline']} (model {h['baseline_model']}, "
              f"{h['baseline_islands_found']} islands, {h['baseline_windows']} windows)")
        print(f"  granularity         : {h['granularity_level']}   "
              f"entity-level layer: {'present' if h['entity_layer_present'] else 'empty'}")
        if h["stage_localisation_rate"] is not None:
            print(f"  correct stage picks : {h['stage_localisation_hits']}/"
                  f"{h['configs_scored']}  ({h['stage_localisation_rate']:.0%})")
            print(f"  mean margin vs #2   : {h['mean_margin_over_runner_up']}")
        print()
        for r in c["rows"]:
            if r["status"] == "FAILED":
                print(f"  {r['config']:<22} FAILED")
                continue
            hit = "HIT " if r["hit"] else ("miss" if r["hit"] is False else "  ? ")
            di = "" if r["delta_islands"] is None else f"  Islands {r['delta_islands']:+d}"
            print(f"  {r['config']:<22} changed [{r['knob']}]  ->  "
                  f"PROXAI blames [{r['predicted_stage']}]  {hit}{di}")
        print(f"\n  full table: {RESULTS_DIR/'_comparison.md'}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--quick", action="store_true", help="2 configs only")
    g.add_argument("--full", action="store_true", help="all 11 configs")
    g.add_argument("--analyze-only", action="store_true",
                   help="skip the runs, just re-analyse stress_test/results/")
    ap.add_argument("--granularity", type=int, default=1)
    ap.add_argument("--dataset", default=DATASET)
    args = ap.parse_args()

    print(hr("PROXAI x SSG-LUGIA  -  stress-test demo"))
    check_neo4j()

    if not args.analyze_only:
        cmd = [sys.executable, "stress_test/run_stress_test.py",
               "--dataset", args.dataset,
               "--granularity_level", str(args.granularity)]
        if args.quick:
            cmd += ["--only", *QUICK_CONFIGS]
        elif not args.full:
            cmd += ["--only", *DEMO_CONFIGS]
        run(cmd)

    run([sys.executable, "stress_test/compare.py"])

    print_figures()
    print(hr("USE CASES"))
    print(USE_CASES)
    print(hr("SHOW THE GRAPH IN NEO4J"))
    print(NEO4J_QUERIES)
    print(hr())
    print("Demo complete. Talking points above; graph is live in Neo4j now.")


if __name__ == "__main__":
    main()
