"""
One-command demo of a PROXAI stress-test profile.

  1. checks Neo4j is reachable
  2. runs a subset of the profile's configs through PROXAI
  3. runs the baseline-vs-config comparison
  4. prints the result table, use cases, and the Neo4j queries to show the graph

Run from the PROXAI repo root, venv active, Neo4j up:

    python stress_test/demo.py                       # ssg_lugia, 4 configs, granularity 1
    python stress_test/demo.py --profile census_ml   # census_ml, 4 configs
    python stress_test/demo.py --quick               # 2 configs
    python stress_test/demo.py --full                # every config in the profile
    python stress_test/demo.py --analyze-only        # skip runs, re-analyse results/

Needs KEY.py with a working Groq key (see README).
"""

import argparse
import importlib
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
RESULTS_DIR = Path(__file__).parent / "results"
sys.path.insert(0, str(Path(__file__).parent))

DEFAULT_DATASET = {
    "ssg_lugia": "external/SSG-LUGIA/codes/sample_data/NC_003198.1.fasta",
    "census_ml": "datasets/census.csv",
}
DEMO_SUBSET = {
    "ssg_lugia": ["baseline_F", "classifier_R", "feature_no_entropy", "window_coarse_20000"],
    "census_ml": ["baseline", "clf_rf", "encode_ordinal", "select_k5"],
}
QUICK_SUBSET = {
    "ssg_lugia": ["baseline_F", "classifier_R"],
    "census_ml": ["baseline", "clf_rf"],
}

USE_CASES = """\
  1. STAGE ATTRIBUTION / ROOT CAUSE
     "The output changed - which stage caused it?"  compare.py ranks every stage
     by how far its provenance diverged from baseline; the top one is the suspect.
  2. CHANGE-PROPAGATION TRACING
     A change to one stage shows large divergence there plus smaller, secondary
     divergence downstream. The graph shows the ripple, not just the origin.
  3. REPRODUCIBILITY / AUDIT
     Every tracked value and the operation that produced/invalidated it is
     recorded; you can point at the exact op behind any cell.
  4. REGRESSION TRIAGE ACROSS A SWEEP
     One table instead of eyeballing N runs: config -> knob -> stage PROXAI
     blames -> actual metric delta.
  5. PIPELINE DOCUMENTATION FROM WHAT RAN
     The auto-extracted activities describe what the pipeline actually did.
  6. PROVENANCE-COST PROFILING
     Node/edge counts per granularity quantify the tracking overhead."""

NEO4J_QUERIES = """\
  Open http://localhost:7474  (Connect URL bolt://localhost:7687, neo4j / adminadmin)
  Paste each, press Ctrl+Enter:

  MATCH p = (c:Column)-[r]-(a:Activity) RETURN p           -- pipeline shape
  MATCH (a:Activity) RETURN a.function_name, a.context     -- stages + what each does
  MATCH p = (:Activity)-[:NEXT]->(:Activity) RETURN p      -- execution order
  MATCH p = (e:Entity)-[:WAS_GENERATED_BY]->(a:Activity) RETURN p LIMIT 100  -- lineage sample
  MATCH (n) RETURN labels(n)[0] AS type, count(*) AS count ORDER BY count DESC -- size"""


def hr(title=""):
    line = "=" * 80
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
        sys.exit(f"Neo4j not reachable ({e}). Start it: cd neo4j && docker compose up -d")
    print("Neo4j: reachable")


def run(cmd):
    print(f"\n$ {' '.join(cmd)}")
    r = subprocess.run(cmd, cwd=REPO_ROOT)
    if r.returncode != 0:
        sys.exit(f"command failed ({r.returncode}): {' '.join(cmd)}")


def print_results():
    summ, comp = RESULTS_DIR / "_summary.json", RESULTS_DIR / "_comparison.json"
    if summ.exists():
        data = json.loads(summ.read_text(encoding="utf-8"))
        print(hr(f"THIS RUN  (profile: {data.get('profile')})"))
        for s in data.get("runs", []):
            ok = "ok  " if s["success"] else "FAIL"
            print(f"  [{ok}] {s['name']:<22} {s['metrics']}")
    if comp.exists():
        c = json.loads(comp.read_text(encoding="utf-8"))
        h = c["headline"]
        print(hr("STAGE-LOCALISATION RESULT"))
        print(f"  baseline           : {h['baseline']}  {h['baseline_metrics']}")
        print(f"  granularity        : {h['granularity_level']}   "
              f"entity-level layer: {'present' if h['entity_layer_present'] else 'empty'}")
        if h["stage_localisation_rate"] is not None:
            print(f"  correct stage picks: {h['stage_localisation_hits']}/"
                  f"{h['configs_scored']}  ({h['stage_localisation_rate']:.0%}), "
                  f"mean margin vs #2 {h['mean_margin_over_runner_up']}")
        print()
        for r in c["rows"]:
            if r["status"] == "FAILED":
                print(f"  {r['config']:<24} FAILED")
                continue
            hit = "HIT " if r["hit"] else ("miss" if r["hit"] is False else "  ? ")
            print(f"  {r['config']:<24} [{r['knob']}]  ->  PROXAI blames "
                  f"[{r['predicted_stage']}]  {hit}  {r['deltas']}")
        print(f"\n  full table: {RESULTS_DIR/'_comparison.md'}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", default="ssg_lugia")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--quick", action="store_true", help="2 configs only")
    g.add_argument("--full", action="store_true", help="every config in the profile")
    g.add_argument("--analyze-only", action="store_true", help="skip runs, re-analyse results/")
    ap.add_argument("--granularity", type=int, default=1)
    ap.add_argument("--dataset", default=None)
    args = ap.parse_args()

    prof = args.profile
    dataset = args.dataset or DEFAULT_DATASET.get(prof)
    if dataset is None:
        sys.exit(f"no default dataset for profile '{prof}' -- pass --dataset")

    print(hr(f"PROXAI stress-test demo  [profile: {prof}]"))
    check_neo4j()

    if not args.analyze_only:
        cmd = [sys.executable, "stress_test/run_stress_test.py",
               "--profile", prof, "--dataset", dataset,
               "--granularity_level", str(args.granularity)]
        if args.quick:
            cmd += ["--only", *QUICK_SUBSET.get(prof, [])]
        elif not args.full:
            cmd += ["--only", *DEMO_SUBSET.get(prof, [])]
        run(cmd)

    run([sys.executable, "stress_test/compare.py", "--profile", prof])

    print_results()
    print(hr("USE CASES"))
    print(USE_CASES)
    print(hr("SHOW THE GRAPH IN NEO4J"))
    print(NEO4J_QUERIES)
    print(hr())
    print("Demo complete. Graph is live in Neo4j now.")


if __name__ == "__main__":
    main()
