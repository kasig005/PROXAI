"""
Stress-test driver for PROXAI x SSG-LUGIA.

Runs prolit_run.py once per config in configs.py. Each config is passed to
pipelines/ssg_lugia_pipeline.py through the SSG_LUGIA_CONFIG env var, so the same
pipeline file runs 11 times with a different stage-by-stage setup each time.

Because prolit_run.py calls neo4j.delete_all() at the start of every run, this
script snapshots each run's provenance graph to results/<config_name>.json
(straight from the Neo4j driver -- no APOC / file-export config needed) right
after that run finishes and before the next run's delete_all() wipes it.

Usage (from the PROXAI repo root, venv active, Neo4j running):

    python stress_test/run_stress_test.py \
        --dataset external/SSG-LUGIA/codes/sample_data/NC_003198.1.fasta

    # just one or two configs while iterating:
    python stress_test/run_stress_test.py --dataset ... --only baseline_F classifier_R

Requires: KEY.py with a working Groq key (see README). Neo4j from
neo4j/docker-compose.yml. Run stress_test/compare.py afterwards to build the
baseline-vs-config comparison.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from configs import CONFIGS

try:
    from neo4j import GraphDatabase
except ImportError:
    GraphDatabase = None

REPO_ROOT = Path(__file__).parent.parent
PIPELINE_SRC = REPO_ROOT / "pipelines" / "ssg_lugia_pipeline.py"
EXTRACTED = REPO_ROOT / "extracted_code.py"

# Parses e.g.:
# [SSG-LUGIA pipeline] model=SSG-LUGIA-F  overrides={}  windows=47991  islands_found=14
_SUMMARY_RE = re.compile(
    r"\[SSG-LUGIA pipeline\].*?windows=(?P<windows>\d+)\s+islands_found=(?P<islands>\d+)"
)


def parse_pipeline_summary(stdout: str):
    """Pull windows / islands_found from the pipeline's own summary line."""
    m = _SUMMARY_RE.search(stdout or "")
    if not m:
        return {"windows": None, "islands_found": None}
    return {
        "windows": int(m.group("windows")),
        "islands_found": int(m.group("islands")),
    }


def clear_graph(uri, user, pwd):
    """
    Empty the graph in bounded batches.

    prolit_run.py's own neo4j.delete_all() is a single unbatched
    `MATCH (n) DETACH DELETE n`; on a large leftover graph that blows Neo4j's
    transaction-memory cap, fails silently, and the next run stacks on top of
    the old data. We clear it ourselves first so each config starts clean.
    """
    if GraphDatabase is None:
        return
    driver = GraphDatabase.driver(uri, auth=(user, pwd))
    try:
        with driver.session() as s:
            before = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            if before == 0:
                return
            # Loop small DETACH DELETE batches until the graph is actually empty.
            # (One apoc.periodic.iterate call can return before it has removed
            # everything; looping a bounded manual delete always converges.)
            remaining = before
            stalls = 0
            for _ in range(100_000):
                s.run("MATCH (n) WITH n LIMIT 10000 DETACH DELETE n").consume()
                now = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
                if now == 0:
                    remaining = 0
                    break
                stalls = stalls + 1 if now >= remaining else 0
                remaining = now
                if stalls >= 5:
                    raise RuntimeError(
                        f"clear_graph stalled with {now} nodes still present"
                    )
            print(f"  cleared graph: {before} -> {remaining} nodes")
            if remaining != 0:
                raise RuntimeError(f"graph not empty after clear ({remaining} nodes left)")
    finally:
        driver.close()


def snapshot_graph(uri, user, pwd):
    """
    Read the current provenance graph via the Neo4j driver and return a compact,
    comparable summary: totals, per-activity entity counts, and the columns each
    activity touches. This is what compare.py diffs against the baseline.
    """
    if GraphDatabase is None:
        return {"error": "neo4j driver not installed"}

    driver = GraphDatabase.driver(uri, auth=(user, pwd))
    try:
        with driver.session() as s:
            totals = {
                "nodes": s.run("MATCH (n) RETURN count(n) AS c").single()["c"],
                "relationships": s.run(
                    "MATCH ()-[r]->() RETURN count(r) AS c"
                ).single()["c"],
                "by_label": {
                    r["l"]: r["c"]
                    for r in s.run(
                        "MATCH (n) UNWIND labels(n) AS l "
                        "RETURN l AS l, count(*) AS c ORDER BY c DESC"
                    )
                },
                "by_rel_type": {
                    r["t"]: r["c"]
                    for r in s.run(
                        "MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS c "
                        "ORDER BY c DESC"
                    )
                },
            }

            # Per-activity entity flow counts.
            act_rows = s.run(
                """
                MATCH (a:Activity)
                OPTIONAL MATCH (a)-[:USED]->(eu:Entity)
                WITH a, count(DISTINCT eu) AS n_used
                OPTIONAL MATCH (eg:Entity)-[:WAS_GENERATED_BY]->(a)
                WITH a, n_used, count(DISTINCT eg) AS n_gen
                OPTIONAL MATCH (ei:Entity)-[:WAS_INVALIDATED_BY]->(a)
                RETURN a.id            AS id,
                       a.function_name AS function_name,
                       a.context       AS context,
                       a.code          AS code,
                       n_used          AS n_entities_used,
                       n_gen           AS n_entities_generated,
                       count(DISTINCT ei) AS n_entities_invalidated
                """
            )
            activities = {}
            for r in act_rows:
                activities[r["id"]] = {
                    "id": r["id"],
                    "function_name": r["function_name"],
                    "context": r["context"],
                    "code": r["code"],
                    "n_entities_used": r["n_entities_used"],
                    "n_entities_generated": r["n_entities_generated"],
                    "n_entities_invalidated": r["n_entities_invalidated"],
                    "columns_used": set(),
                    "columns_generated": set(),
                    "columns_invalidated": set(),
                    "order_index": None,
                }

            # Column-level edges (present at every granularity, small + stable).
            col_edges = s.run(
                """
                MATCH (a:Activity)-[:USED]->(c:Column)
                RETURN a.id AS aid, 'used' AS kind, c.name AS col
                UNION ALL
                MATCH (c:Column)-[:WAS_GENERATED_BY]->(a:Activity)
                RETURN a.id AS aid, 'generated' AS kind, c.name AS col
                UNION ALL
                MATCH (c:Column)-[:WAS_INVALIDATED_BY]->(a:Activity)
                RETURN a.id AS aid, 'invalidated' AS kind, c.name AS col
                """
            )
            for r in col_edges:
                a = activities.get(r["aid"])
                if a is None or r["col"] is None:
                    continue
                a["columns_" + r["kind"]].add(r["col"])

            # Execution order from the NEXT chain.
            nxt = {
                r["from"]: r["to"]
                for r in s.run(
                    "MATCH (a:Activity)-[:NEXT]->(b:Activity) "
                    "RETURN a.id AS from, b.id AS to"
                )
            }
            starts = set(activities) - set(nxt.values())
            order, seen = [], set()
            for start in starts:
                cur = start
                while cur is not None and cur not in seen:
                    seen.add(cur)
                    order.append(cur)
                    cur = nxt.get(cur)
            for aid in activities:  # any left over (no NEXT edges at all)
                if aid not in seen:
                    order.append(aid)
            for i, aid in enumerate(order):
                if aid in activities:
                    activities[aid]["order_index"] = i

            # JSON-friendly: sets -> sorted lists, dict -> ordered list.
            act_list = []
            for aid in order:
                a = activities.get(aid)
                if a is None:
                    continue
                a["columns_used"] = sorted(a["columns_used"])
                a["columns_generated"] = sorted(a["columns_generated"])
                a["columns_invalidated"] = sorted(a["columns_invalidated"])
                act_list.append(a)

            return {"graph_totals": totals, "activities": act_list}
    finally:
        driver.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", required=True, help="Path to the genome fasta file")
    parser.add_argument("--pipeline", default="pipelines/ssg_lugia_pipeline.py")
    parser.add_argument(
        "--granularity_level", type=int, default=1,
        help="PROXAI granularity 1-4. Default 1 (Sketch). Level 3 (Full) produces "
             "~750k nodes / ~2.5M rels PER run on this genome -- only use it for a "
             "single run, not the 11-config sweep.",
    )
    parser.add_argument("--only", nargs="+", metavar="CONFIG_NAME", default=None,
                        help="Run only these config names (default: all 11).")
    parser.add_argument("--neo4j_uri", default="bolt://localhost:7687")
    parser.add_argument("--neo4j_user", default="neo4j")
    parser.add_argument("--neo4j_pwd", default="adminadmin")
    args = parser.parse_args()

    configs = CONFIGS
    if args.only:
        wanted = set(args.only)
        configs = [c for c in CONFIGS if c["name"] in wanted]
        missing = wanted - {c["name"] for c in configs}
        if missing:
            parser.error(f"unknown config name(s): {sorted(missing)}")

    results_dir = REPO_ROOT / "stress_test" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    # prolit_run.py --use_manual_code executes the file named extracted_code.py,
    # NOT --pipeline. Put our pipeline there. It reads its per-run config from the
    # SSG_LUGIA_CONFIG env var, so copying once up front is enough.
    shutil.copyfile(PIPELINE_SRC, EXTRACTED)
    print(f"Copied {PIPELINE_SRC.name} -> {EXTRACTED.name}")

    summary = []
    for cfg in configs:
        print(f"\n=== Running config: {cfg['name']} "
              f"(model={cfg['model_name']}, overrides={cfg['overrides']}) ===")

        # prolit_run.py calls its own delete_all(), but that is fragile on a
        # large graph -- clear it robustly here first.
        clear_graph(args.neo4j_uri, args.neo4j_user, args.neo4j_pwd)

        env = os.environ.copy()
        env["SSG_LUGIA_CONFIG"] = json.dumps(
            {"model_name": cfg["model_name"], "overrides": cfg["overrides"]}
        )
        # Windows console is cp1252; the LLM step prints non-ASCII -> force UTF-8.
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"

        proc = subprocess.run(
            [
                sys.executable, "prolit_run.py",
                "--dataset", args.dataset,
                "--pipeline", args.pipeline,
                "--frac", "1.0",
                "--granularity_level", str(args.granularity_level),
                "--use_manual_code",
            ],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

        ok = proc.returncode == 0
        print(proc.stdout[-2000:])
        if not ok:
            print("--- STDERR (tail) ---")
            print(proc.stderr[-3000:])

        pipe_summary = parse_pipeline_summary(proc.stdout)
        out_path = results_dir / f"{cfg['name']}.json"
        record = {
            "config": {
                "name": cfg["name"],
                "model_name": cfg["model_name"],
                "overrides": cfg["overrides"],
            },
            "granularity_level": args.granularity_level,
            "success": ok,
            "returncode": proc.returncode,
            "pipeline": pipe_summary,
        }

        if ok:
            try:
                record.update(
                    snapshot_graph(args.neo4j_uri, args.neo4j_user, args.neo4j_pwd)
                )
            except Exception as e:  # noqa: BLE001
                record["snapshot_error"] = repr(e)
                print(f"  [!] graph snapshot failed: {e!r}")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(record, f, indent=2)
            print(f"  -> {out_path.relative_to(REPO_ROOT)}  "
                  f"(windows={pipe_summary['windows']}, "
                  f"islands_found={pipe_summary['islands_found']})")
        else:
            # still write the record so compare.py / a human can see it failed
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(record, f, indent=2)
            print(f"  [FAILED] see {out_path.relative_to(REPO_ROOT)}")

        summary.append({
            "name": cfg["name"],
            "model_name": cfg["model_name"],
            "overrides": cfg["overrides"],
            "success": ok,
            "windows": pipe_summary["windows"],
            "islands_found": pipe_summary["islands_found"],
            "result_file": str(out_path.relative_to(REPO_ROOT)) if ok else None,
        })

    with open(results_dir / "_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("\n\n=== Stress test complete ===")
    for s in summary:
        status = "OK  " if s["success"] else "FAIL"
        print(f"  [{status}] {s['name']:24s} "
              f"windows={s['windows']} islands_found={s['islands_found']}")
    print(f"\nResults in {results_dir.relative_to(REPO_ROOT)}/")
    print("Next: python stress_test/compare.py")


if __name__ == "__main__":
    main()
