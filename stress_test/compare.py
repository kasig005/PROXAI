"""
Compare each stress-test config's provenance graph against the baseline.

The point of the SSG-LUGIA stress test: every non-baseline config changes exactly
ONE pipeline stage, so we know which stage *should* explain any behaviour change.
This script checks whether PROXAI's provenance graph agrees -- i.e. whether the
stage whose provenance diverges most from baseline is the stage we actually
changed. That is the "automate the manual per-stage digging" deliverable.

Input : stress_test/results/<config>.json  (written by run_stress_test.py)
Output: - a table on stdout
        - stress_test/results/_comparison.json
        - stress_test/results/_comparison.md

No dependencies beyond the standard library.

    python stress_test/compare.py
"""

import argparse
import json
import statistics
from pathlib import Path

RESULTS_DIR = Path(__file__).parent / "results"
BASELINE_NAME = "baseline_F"

# --- map each activity onto one of the 4 SSG-LUGIA stages --------------------
# Primary signal: the activity's *code* (deterministic -- the pipeline's stage
# calls are fixed). Fallback: the LLM's freeform function_name (noisy, varies
# run-to-run). Checked in STAGE_ORDER; first hit wins.
STAGE_ORDER = ["islands", "post_processing", "anomaly_detection", "feature_extraction"]
STAGE_CODE_KEYWORDS = {
    "islands": [
        "getgenomicislands", "in_predicted_island", "df_islands", "per_base_label",
        "trimregions", "inferlabel", "island_start", "island_end",
    ],
    "post_processing": [
        "medianfiltering", "binaizefiltereddistance", "binarizefiltereddistance",
        "score_median_filtered", "pred_binarized", "ys_median_filtered",
        "yp_binarized", "ys_mf", "yp_mf", "df_postproc",
    ],
    "anomaly_detection": [
        "detectanomalies", "anomaly_pred", "anomaly_score", "df_anomaly",
    ],
    "feature_extraction": [
        "extractfeatures", "df_features", "feat_", "x[:,", "x.shape",
    ],
}
STAGE_KEYWORDS = {
    "islands": [
        "island", "genomic region", "getgenomicislands",
    ],
    "post_processing": [
        "median", "filter", "binar", "binaiz", "infer label", "inferlabel",
        "trim", "smooth", "post-process", "postprocess",
    ],
    "anomaly_detection": [
        "anomal", "detect", "classif", "novelty", "outlier", "predict",
        "one-class", "oneclass", "isolation", "lof", "svm", "elliptic", "score",
    ],
    "feature_extraction": [
        "feature", "extract", "window", "karlin", "entropy", "pca", "kmer",
        "k-mer", "amino", "codon", "gc content", "composition",
        "tetranucleotide", "dinucleotide",
    ],
}
STAGE_LABEL = {
    "feature_extraction": "feature extraction",
    "anomaly_detection": "anomaly detection",
    "post_processing": "post-processing",
    "islands": "islands",
    "other": "(unclassified)",
}

# which override keys / model changes point at which stage
FEATURE_KEYS = {"w", "dw", "karlin_mode", "entropy_features",
                "pca_dn", "pca_amino_acid", "pca_kmer4"}


def classify_activity(activity: dict) -> str:
    code = (activity.get("code") or "").lower()
    for stage in STAGE_ORDER:
        if any(k in code for k in STAGE_CODE_KEYWORDS[stage]):
            return stage
    fn = (activity.get("function_name") or "").lower()
    for stage in STAGE_ORDER:
        if any(k in fn for k in STAGE_KEYWORDS[stage]):
            return stage
    return "other"


def expected_stage(cfg: dict, baseline_model: str) -> str:
    overrides = cfg.get("overrides") or {}
    model = cfg.get("model_name")
    if not overrides and model == baseline_model:
        return "baseline"
    if not overrides and model != baseline_model:
        return "anomaly_detection"          # classifier variant F/R/P
    if set(overrides) & FEATURE_KEYS:
        return "feature_extraction"         # scanning resolution / feature repr
    return "unknown"


def knob_description(cfg: dict, baseline_model: str) -> str:
    overrides = cfg.get("overrides") or {}
    if not overrides:
        if cfg.get("model_name") != baseline_model:
            return f"classifier = {cfg['model_name']}"
        return "(baseline)"
    return ", ".join(f"{k}={v}" for k, v in overrides.items())


# --- fingerprints -------------------------------------------------------------
def stage_fingerprints(record: dict) -> dict:
    """Aggregate a record's activities into per-stage fingerprints."""
    fp = {s: {
        "columns_used": set(), "columns_generated": set(), "columns_invalidated": set(),
        "n_entities_used": 0, "n_entities_generated": 0, "n_entities_invalidated": 0,
        "n_activities": 0, "activity_names": [],
    } for s in STAGE_ORDER + ["other"]}

    for act in record.get("activities", []):
        stage = classify_activity(act)
        b = fp[stage]
        b["columns_used"].update(act.get("columns_used", []))
        b["columns_generated"].update(act.get("columns_generated", []))
        b["columns_invalidated"].update(act.get("columns_invalidated", []))
        b["n_entities_used"] += act.get("n_entities_used", 0) or 0
        b["n_entities_generated"] += act.get("n_entities_generated", 0) or 0
        b["n_entities_invalidated"] += act.get("n_entities_invalidated", 0) or 0
        b["n_activities"] += 1
        b["activity_names"].append(act.get("function_name"))
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


def stage_divergence(base_fp: dict, cfg_fp: dict) -> float:
    """
    0 = identical provenance for this stage, 1 = completely different.
    0.5 * column-set change  +  0.4 * entity-volume change  +  0.1 * op-count change
    """
    col_dists = [
        d for d in (
            _jaccard_distance(base_fp["columns_used"], cfg_fp["columns_used"]),
            _jaccard_distance(base_fp["columns_generated"], cfg_fp["columns_generated"]),
            _jaccard_distance(base_fp["columns_invalidated"], cfg_fp["columns_invalidated"]),
        ) if d is not None
    ]
    col_term = statistics.fmean(col_dists) if col_dists else 0.0

    cnt_term = statistics.fmean([
        _rel_diff(base_fp["n_entities_used"], cfg_fp["n_entities_used"]),
        _rel_diff(base_fp["n_entities_generated"], cfg_fp["n_entities_generated"]),
        _rel_diff(base_fp["n_entities_invalidated"], cfg_fp["n_entities_invalidated"]),
    ])
    act_term = _rel_diff(base_fp["n_activities"], cfg_fp["n_activities"])

    return round(0.5 * col_term + 0.4 * cnt_term + 0.1 * act_term, 4)


# --- load / drive ------------------------------------------------------------
def load_records(results_dir: Path) -> dict:
    out = {}
    for p in sorted(results_dir.glob("*.json")):
        if p.name.startswith("_"):
            continue
        with open(p, encoding="utf-8") as f:
            rec = json.load(f)
        out[rec["config"]["name"]] = rec
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results-dir", default=str(RESULTS_DIR))
    ap.add_argument("--baseline", default=BASELINE_NAME)
    args = ap.parse_args()

    results_dir = Path(args.results_dir)
    records = load_records(results_dir)
    if not records:
        ap.error(f"no result files in {results_dir} -- run run_stress_test.py first")
    if args.baseline not in records:
        ap.error(f"baseline '{args.baseline}' not found. Have: {sorted(records)}")

    base = records[args.baseline]
    if not base.get("success"):
        ap.error(f"baseline run '{args.baseline}' did not succeed -- cannot compare")
    baseline_model = base["config"]["model_name"]
    base_fp = stage_fingerprints(base)
    base_islands = (base.get("pipeline") or {}).get("islands_found")
    base_windows = (base.get("pipeline") or {}).get("windows")

    entity_layer_present = any(
        base_fp[s]["n_entities_used"] or base_fp[s]["n_entities_generated"]
        for s in STAGE_ORDER
    )

    rows = []
    for name, rec in records.items():
        if name == args.baseline:
            continue
        cfg = rec["config"]
        exp = expected_stage(cfg, baseline_model)
        knob = knob_description(cfg, baseline_model)

        if not rec.get("success"):
            rows.append({
                "config": name, "knob": knob, "expected_stage": exp,
                "status": "FAILED", "predicted_stage": None, "hit": None,
                "margin": None, "runner_up": None,
                "stage_scores": {}, "delta_islands": None, "delta_windows": None,
            })
            continue

        cfg_fp = stage_fingerprints(rec)
        scores = {s: stage_divergence(base_fp[s], cfg_fp[s]) for s in STAGE_ORDER}
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        predicted, top_score = ranked[0]
        runner_up, second_score = ranked[1] if len(ranked) > 1 else (None, 0.0)
        margin = round(top_score - second_score, 4)
        if top_score == 0.0:
            predicted = None  # nothing diverged at all

        pipe = rec.get("pipeline") or {}
        rows.append({
            "config": name,
            "knob": knob,
            "expected_stage": exp,
            "status": "ok",
            "predicted_stage": predicted,
            "hit": (predicted == exp) if predicted and exp in STAGE_ORDER else None,
            "margin": margin,
            "runner_up": runner_up,
            "stage_scores": scores,
            "delta_islands": (None if pipe.get("islands_found") is None or base_islands is None
                              else pipe["islands_found"] - base_islands),
            "delta_windows": (None if pipe.get("windows") is None or base_windows is None
                              else pipe["windows"] - base_windows),
        })

    rows.sort(key=lambda r: r["config"])

    scored = [r for r in rows if r["hit"] is not None]
    hits = sum(1 for r in scored if r["hit"])
    headline = {
        "baseline": args.baseline,
        "baseline_model": baseline_model,
        "baseline_islands_found": base_islands,
        "baseline_windows": base_windows,
        "granularity_level": base.get("granularity_level"),
        "entity_layer_present": entity_layer_present,
        "configs_compared": len(rows),
        "configs_scored": len(scored),
        "stage_localisation_hits": hits,
        "stage_localisation_rate": (round(hits / len(scored), 3) if scored else None),
        "mean_margin_over_runner_up": (round(statistics.fmean([r["margin"] for r in scored]), 4)
                                       if scored else None),
    }

    out = {"headline": headline, "rows": rows}
    (results_dir / "_comparison.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    _write_markdown(results_dir / "_comparison.md", headline, rows)
    _print_table(headline, rows)
    print(f"\nWrote {results_dir/'_comparison.json'} and {results_dir/'_comparison.md'}")


# --- rendering -------------------------------------------------------------
def _fmt_stage(s):
    return STAGE_LABEL.get(s, s or "-")


def _print_table(headline, rows):
    print("\n" + "=" * 78)
    print("PROXAI x SSG-LUGIA  -  provenance stage localisation")
    print("=" * 78)
    print(f"baseline            : {headline['baseline']} "
          f"(model {headline['baseline_model']}, "
          f"islands={headline['baseline_islands_found']}, "
          f"windows={headline['baseline_windows']}, "
          f"granularity {headline['granularity_level']})")
    print(f"entity-level layer  : {'present' if headline['entity_layer_present'] else 'EMPTY (raise granularity for a stronger signal)'}")
    if headline["stage_localisation_rate"] is not None:
        print(f"stage localisation  : {headline['stage_localisation_hits']}/"
              f"{headline['configs_scored']} correct "
              f"({headline['stage_localisation_rate']:.0%}), "
              f"mean margin over runner-up {headline['mean_margin_over_runner_up']}")
    print("-" * 78)
    hdr = f"{'config':<24} {'knob changed':<22} {'expected':<18} {'PROXAI #1':<18} {'hit':<4} {'Δisl':>5} {'Δwin':>7}"
    print(hdr)
    print("-" * 78)
    for r in rows:
        if r["status"] == "FAILED":
            print(f"{r['config']:<24} {r['knob']:<22} {_fmt_stage(r['expected_stage']):<18} {'-- run failed --':<18} {'-':<4} {'-':>5} {'-':>7}")
            continue
        hit = "yes" if r["hit"] else ("no" if r["hit"] is False else "?")
        di = "-" if r["delta_islands"] is None else f"{r['delta_islands']:+d}"
        dw = "-" if r["delta_windows"] is None else f"{r['delta_windows']:+d}"
        print(f"{r['config']:<24} {r['knob']:<22} {_fmt_stage(r['expected_stage']):<18} "
              f"{_fmt_stage(r['predicted_stage']):<18} {hit:<4} {di:>5} {dw:>7}")
    print("-" * 78)
    print("Δisl = islands_found - baseline ;  Δwin = windows - baseline")
    print("'hit' = the stage whose provenance diverged most from baseline is the")
    print("        stage this config actually changed.")


def _write_markdown(path, headline, rows):
    L = []
    L.append("# PROXAI × SSG-LUGIA — provenance stage localisation\n")
    L.append(f"- **Baseline:** `{headline['baseline']}` — model {headline['baseline_model']}, "
             f"{headline['baseline_islands_found']} islands, {headline['baseline_windows']} windows, "
             f"granularity {headline['granularity_level']}")
    L.append(f"- **Entity-level provenance layer:** "
             f"{'present' if headline['entity_layer_present'] else '**empty** — rerun at higher `--granularity_level` for a stronger signal'}")
    if headline["stage_localisation_rate"] is not None:
        L.append(f"- **Stage localisation:** {headline['stage_localisation_hits']}/"
                 f"{headline['configs_scored']} configs correct "
                 f"({headline['stage_localisation_rate']:.0%}); "
                 f"mean divergence margin over the runner-up stage "
                 f"{headline['mean_margin_over_runner_up']}")
    L.append("")
    L.append("| config | knob changed | expected stage | PROXAI top-diverged stage | hit | Δislands | Δwindows | margin |")
    L.append("|---|---|---|---|:--:|--:|--:|--:|")
    for r in rows:
        if r["status"] == "FAILED":
            L.append(f"| `{r['config']}` | {r['knob']} | {_fmt_stage(r['expected_stage'])} | _run failed_ | – | – | – | – |")
            continue
        hit = "✅" if r["hit"] else ("❌" if r["hit"] is False else "–")
        di = "–" if r["delta_islands"] is None else f"{r['delta_islands']:+d}"
        dw = "–" if r["delta_windows"] is None else f"{r['delta_windows']:+d}"
        L.append(f"| `{r['config']}` | {r['knob']} | {_fmt_stage(r['expected_stage'])} | "
                 f"{_fmt_stage(r['predicted_stage'])} | {hit} | {di} | {dw} | {r['margin']} |")
    L.append("")
    L.append("## Per-config stage divergence scores\n")
    L.append("Divergence from baseline for each stage (0 = identical provenance, 1 = fully changed).\n")
    for r in rows:
        if not r["stage_scores"]:
            continue
        L.append(f"### `{r['config']}` — changed {r['knob']}")
        ordered = sorted(r["stage_scores"].items(), key=lambda kv: kv[1], reverse=True)
        for stage, sc in ordered:
            mark = " ← expected" if stage == r["expected_stage"] else ""
            L.append(f"- {_fmt_stage(stage)}: **{sc}**{mark}")
        L.append("")
    path.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
