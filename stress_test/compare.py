"""
Compare each stress-test config's provenance graph against the baseline.

Every non-baseline config changes exactly ONE pipeline stage, so we know which
stage *should* explain any behaviour change. This checks whether PROXAI's
provenance graph agrees: is the stage whose provenance diverges most from
baseline the stage we actually changed? That is the "automate the manual
per-stage digging" deliverable.

The stage set + activity->stage mapping + expected-stage logic come from the
profile module (stress_test/<profile>.py), so this works for any pipeline.

Input : stress_test/results/<config>.json  (written by run_stress_test.py)
Output: table on stdout + results/_comparison.{json,md}

    python stress_test/compare.py --profile ssg_lugia
    python stress_test/compare.py --profile census_ml

Standard library only.
"""

import argparse
import importlib
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
RESULTS_DIR = Path(__file__).parent / "results"


# --- profile-driven activity -> stage classification -------------------------
def make_classifier(profile):
    stages = profile.STAGES
    code_kw = profile.STAGE_CODE_KEYWORDS
    name_kw = getattr(profile, "STAGE_NAME_KEYWORDS", {})

    def classify(activity: dict) -> str:
        code = (activity.get("code") or "").lower()
        for stage in stages:
            if any(k in code for k in code_kw.get(stage, [])):
                return stage
        fn = (activity.get("function_name") or "").lower()
        for stage in stages:
            if any(k in fn for k in name_kw.get(stage, [])):
                return stage
        return "other"

    return classify


def stage_label(profile, s):
    return getattr(profile, "STAGE_LABEL", {}).get(s, s or "-")


# --- fingerprints (generic) -------------------------------------------------
def stage_fingerprints(record, stages, classify):
    fp = {s: {
        "columns_used": set(), "columns_generated": set(), "columns_invalidated": set(),
        "n_entities_used": 0, "n_entities_generated": 0, "n_entities_invalidated": 0,
        "n_activities": 0,
    } for s in list(stages) + ["other"]}

    for act in record.get("activities", []):
        b = fp[classify(act)]
        b["columns_used"].update(act.get("columns_used", []))
        b["columns_generated"].update(act.get("columns_generated", []))
        b["columns_invalidated"].update(act.get("columns_invalidated", []))
        b["n_entities_used"] += act.get("n_entities_used", 0) or 0
        b["n_entities_generated"] += act.get("n_entities_generated", 0) or 0
        b["n_entities_invalidated"] += act.get("n_entities_invalidated", 0) or 0
        b["n_activities"] += 1
    return fp


def _jaccard_distance(a, b):
    a, b = set(a), set(b)
    if not a and not b:
        return None
    return 1.0 - len(a & b) / len(a | b)


def _rel_diff(x, y):
    if x == 0 and y == 0:
        return 0.0
    return abs(x - y) / max(x, y, 1)


def stage_divergence(base_fp, cfg_fp) -> float:
    """0 = identical provenance for this stage, 1 = completely different.
    0.5 * column-set change + 0.4 * entity-volume change + 0.1 * op-count change."""
    col_dists = [d for d in (
        _jaccard_distance(base_fp["columns_used"], cfg_fp["columns_used"]),
        _jaccard_distance(base_fp["columns_generated"], cfg_fp["columns_generated"]),
        _jaccard_distance(base_fp["columns_invalidated"], cfg_fp["columns_invalidated"]),
    ) if d is not None]
    col_term = statistics.fmean(col_dists) if col_dists else 0.0
    cnt_term = statistics.fmean([
        _rel_diff(base_fp["n_entities_used"], cfg_fp["n_entities_used"]),
        _rel_diff(base_fp["n_entities_generated"], cfg_fp["n_entities_generated"]),
        _rel_diff(base_fp["n_entities_invalidated"], cfg_fp["n_entities_invalidated"]),
    ])
    act_term = _rel_diff(base_fp["n_activities"], cfg_fp["n_activities"])
    return round(0.5 * col_term + 0.4 * cnt_term + 0.1 * act_term, 4)


def load_records(results_dir: Path) -> dict:
    out = {}
    for p in sorted(results_dir.glob("*.json")):
        if p.name.startswith("_"):
            continue
        rec = json.loads(p.read_text(encoding="utf-8"))
        out[rec["config"]["name"]] = rec
    return out


def _metric_delta(rec, base, key):
    a = (rec.get("metrics") or {}).get(key)
    b = (base.get("metrics") or {}).get(key)
    if a is None or b is None:
        return None
    d = a - b
    return round(d, 4) if isinstance(d, float) else d


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", default="ssg_lugia")
    ap.add_argument("--results-dir", default=str(RESULTS_DIR))
    ap.add_argument("--baseline", default=None, help="override profile.BASELINE")
    args = ap.parse_args()

    profile = importlib.import_module(args.profile)
    stages = list(profile.STAGES)
    classify = make_classifier(profile)
    baseline_name = args.baseline or profile.BASELINE
    metric_keys = list(profile.METRIC_KEYS)

    results_dir = Path(args.results_dir)
    records = load_records(results_dir)
    if not records:
        ap.error(f"no result files in {results_dir} -- run run_stress_test.py first")
    if baseline_name not in records:
        ap.error(f"baseline '{baseline_name}' not found. Have: {sorted(records)}")
    base = records[baseline_name]
    if not base.get("success"):
        ap.error(f"baseline run '{baseline_name}' did not succeed -- cannot compare")

    base_fp = stage_fingerprints(base, stages, classify)
    entity_layer_present = any(
        base_fp[s]["n_entities_used"] or base_fp[s]["n_entities_generated"] for s in stages
    )

    rows = []
    for name, rec in records.items():
        if name == baseline_name:
            continue
        cfg = rec["config"]
        exp = profile.expected_stage(cfg)
        knob = profile.knob_label(cfg)
        deltas = {k: _metric_delta(rec, base, k) for k in metric_keys}

        if not rec.get("success"):
            rows.append({"config": name, "knob": knob, "expected_stage": exp,
                         "status": "FAILED", "predicted_stage": None, "hit": None,
                         "margin": None, "stage_scores": {}, "deltas": deltas})
            continue

        cfg_fp = stage_fingerprints(rec, stages, classify)
        scores = {s: stage_divergence(base_fp[s], cfg_fp[s]) for s in stages}
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        predicted, top = ranked[0]
        runner_up, second = ranked[1] if len(ranked) > 1 else (None, 0.0)
        if top == 0.0:
            predicted = None
        rows.append({
            "config": name, "knob": knob, "expected_stage": exp, "status": "ok",
            "predicted_stage": predicted,
            "hit": (predicted == exp) if predicted and exp in stages else None,
            "margin": round(top - second, 4), "runner_up": runner_up,
            "stage_scores": scores, "deltas": deltas,
        })

    rows.sort(key=lambda r: r["config"])
    scored = [r for r in rows if r["hit"] is not None]
    hits = sum(1 for r in scored if r["hit"])
    headline = {
        "profile": args.profile,
        "baseline": baseline_name,
        "baseline_metrics": base.get("metrics"),
        "granularity_level": base.get("granularity_level"),
        "entity_layer_present": entity_layer_present,
        "metric_keys": metric_keys,
        "configs_compared": len(rows),
        "configs_scored": len(scored),
        "stage_localisation_hits": hits,
        "stage_localisation_rate": round(hits / len(scored), 3) if scored else None,
        "mean_margin_over_runner_up": (
            round(statistics.fmean([r["margin"] for r in scored]), 4) if scored else None),
    }

    out = {"headline": headline, "rows": rows}
    (results_dir / "_comparison.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    _write_markdown(results_dir / "_comparison.md", headline, rows, profile)
    _print_table(headline, rows, profile)
    print(f"\nWrote {results_dir/'_comparison.json'} and {results_dir/'_comparison.md'}")


# --- rendering -------------------------------------------------------------
def _print_table(h, rows, profile):
    print("\n" + "=" * 82)
    print(f"PROXAI stress test  -  provenance stage localisation  [profile: {h['profile']}]")
    print("=" * 82)
    print(f"baseline           : {h['baseline']}  metrics={h['baseline_metrics']}  "
          f"granularity {h['granularity_level']}")
    print(f"entity-level layer : {'present' if h['entity_layer_present'] else 'EMPTY (raise granularity)'}")
    if h["stage_localisation_rate"] is not None:
        print(f"stage localisation : {h['stage_localisation_hits']}/{h['configs_scored']} "
              f"correct ({h['stage_localisation_rate']:.0%}), "
              f"mean margin over runner-up {h['mean_margin_over_runner_up']}")
    print("-" * 82)
    mk = h["metric_keys"]
    print(f"{'config':<24} {'knob changed':<26} {'expected':<20} {'PROXAI #1':<20} {'hit':<4} "
          + " ".join(f"Δ{k}" for k in mk))
    print("-" * 82)
    for r in rows:
        exp = profile.STAGE_LABEL.get(r["expected_stage"], r["expected_stage"])
        if r["status"] == "FAILED":
            print(f"{r['config']:<24} {r['knob']:<26} {exp:<20} {'-- run failed --':<20}")
            continue
        pred = profile.STAGE_LABEL.get(r["predicted_stage"], r["predicted_stage"] or "-")
        hit = "yes" if r["hit"] else ("no" if r["hit"] is False else "?")
        ds = "  ".join(f"{r['deltas'].get(k)!s:>8}" for k in mk)
        print(f"{r['config']:<24} {r['knob']:<26} {exp:<20} {pred:<20} {hit:<4} {ds}")
    print("-" * 82)
    print("'hit' = the stage whose provenance diverged most from baseline is the one this config changed.")


def _write_markdown(path, h, rows, profile):
    L = [f"# PROXAI stress test — stage localisation  (`{h['profile']}`)\n"]
    L.append(f"- **Baseline:** `{h['baseline']}` — metrics {h['baseline_metrics']}, "
             f"granularity {h['granularity_level']}")
    L.append(f"- **Entity-level provenance layer:** "
             f"{'present' if h['entity_layer_present'] else '**empty** — rerun at higher `--granularity_level`'}")
    if h["stage_localisation_rate"] is not None:
        L.append(f"- **Stage localisation:** {h['stage_localisation_hits']}/{h['configs_scored']} "
                 f"correct ({h['stage_localisation_rate']:.0%}); mean margin over runner-up "
                 f"{h['mean_margin_over_runner_up']}")
    L.append("")
    mk = h["metric_keys"]
    L.append("| config | knob changed | expected stage | PROXAI top-diverged | hit | "
             + " | ".join(f"Δ{k}" for k in mk) + " | margin |")
    L.append("|---|---|---|---|:--:|" + "--:|" * len(mk) + "--:|")
    for r in rows:
        exp = profile.STAGE_LABEL.get(r["expected_stage"], r["expected_stage"])
        if r["status"] == "FAILED":
            L.append(f"| `{r['config']}` | {r['knob']} | {exp} | _run failed_ | – | "
                     + " | ".join("–" for _ in mk) + " | – |")
            continue
        pred = profile.STAGE_LABEL.get(r["predicted_stage"], r["predicted_stage"] or "-")
        hit = "✅" if r["hit"] else ("❌" if r["hit"] is False else "–")
        ds = " | ".join(f"{r['deltas'].get(k)}" for k in mk)
        L.append(f"| `{r['config']}` | {r['knob']} | {exp} | {pred} | {hit} | {ds} | {r['margin']} |")
    L.append("\n## Per-config stage divergence scores\n")
    L.append("Divergence from baseline per stage (0 = identical provenance, 1 = fully changed).\n")
    for r in rows:
        if not r["stage_scores"]:
            continue
        L.append(f"### `{r['config']}` — changed {r['knob']}")
        for stage, sc in sorted(r["stage_scores"].items(), key=lambda kv: kv[1], reverse=True):
            mark = " ← expected" if stage == r["expected_stage"] else ""
            L.append(f"- {profile.STAGE_LABEL.get(stage, stage)}: **{sc}**{mark}")
        L.append("")
    path.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
