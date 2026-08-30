"""
Stress-test profile: SSG-LUGIA genomic-island prediction.

A profile bundles everything run_stress_test.py / compare.py need to drive one
pipeline: the config list, which adapter file to run, the env var to pass config
through, the summary line to parse, and how to map activities <-> stages.
"""

# --- what to run -----------------------------------------------------------
PIPELINE_FILE = "pipelines/ssg_lugia_pipeline.py"
CONFIG_ENV = "SSG_LUGIA_CONFIG"
SUMMARY_PREFIX = "[SSG-LUGIA pipeline]"
METRIC_KEYS = ["windows", "islands_found"]      # pulled from the summary line
BASELINE = "baseline_F"


def config_payload(cfg):
    """The JSON object handed to the pipeline via CONFIG_ENV."""
    return {
        "model_name": cfg.get("model_name", "SSG-LUGIA-F"),
        "overrides": cfg.get("overrides", {}),
    }


CONFIGS = [
    # --- baseline ---
    {"name": "baseline_F",              "model_name": "SSG-LUGIA-F", "overrides": {}},

    # --- classifier variant stage (anomaly detection) ---
    {"name": "classifier_R",            "model_name": "SSG-LUGIA-R", "overrides": {}},
    {"name": "classifier_P",            "model_name": "SSG-LUGIA-P", "overrides": {}},

    # --- window size / scanning resolution stage (feature extraction) ---
    {"name": "window_coarse_20000",     "model_name": "SSG-LUGIA-F", "overrides": {"w": 20000, "dw": 200}},
    {"name": "window_fine_5000",        "model_name": "SSG-LUGIA-F", "overrides": {"w": 5000,  "dw": 50}},
    {"name": "window_very_fine_1000",   "model_name": "SSG-LUGIA-F", "overrides": {"w": 1000,  "dw": 10}},
    {"name": "step_dense_25",           "model_name": "SSG-LUGIA-F", "overrides": {"dw": 25}},

    # --- feature representation stage (feature extraction) ---
    {"name": "feature_karlin_raw",      "model_name": "SSG-LUGIA-F", "overrides": {"karlin_mode": "raw"}},
    {"name": "feature_karlin_original", "model_name": "SSG-LUGIA-F", "overrides": {"karlin_mode": "original"}},
    {"name": "feature_no_entropy",      "model_name": "SSG-LUGIA-F", "overrides": {"entropy_features": False}},
    {"name": "feature_more_pca",        "model_name": "SSG-LUGIA-F", "overrides": {"pca_dn": 5, "pca_amino_acid": 5, "pca_kmer4": 5}},
]

# --- activity -> stage mapping ------------------------------------------------
# Checked in STAGES order; first code-substring hit wins (so "median filter
# anomaly scores" lands in post_processing, not anomaly_detection).
STAGES = ["islands", "post_processing", "anomaly_detection", "feature_extraction"]

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

STAGE_LABEL = {
    "feature_extraction": "feature extraction",
    "anomaly_detection": "anomaly detection",
    "post_processing": "post-processing",
    "islands": "islands",
    "other": "(unclassified)",
    "baseline": "baseline",
    "unknown": "unknown",
}

# fallback when an activity's code matches nothing: match the LLM's function_name
STAGE_NAME_KEYWORDS = {
    "islands": ["island", "genomic region"],
    "post_processing": ["median", "filter", "binar", "binaiz", "infer label",
                        "trim", "smooth", "post-process", "postprocess"],
    "anomaly_detection": ["anomal", "detect", "classif", "novelty", "outlier",
                          "one-class", "isolation", "elliptic", "mahalanobis"],
    "feature_extraction": ["feature", "extract", "window", "karlin", "entropy",
                           "pca", "kmer", "k-mer", "amino", "codon", "gc content",
                           "composition", "dinucleotide"],
}

_FEATURE_KEYS = {"w", "dw", "karlin_mode", "entropy_features",
                 "pca_dn", "pca_amino_acid", "pca_kmer4"}


def expected_stage(cfg):
    overrides = cfg.get("overrides") or {}
    model = cfg.get("model_name")
    if not overrides and model == "SSG-LUGIA-F":
        return "baseline"
    if not overrides and model != "SSG-LUGIA-F":
        return "anomaly_detection"          # classifier variant F/R/P
    if set(overrides) & _FEATURE_KEYS:
        return "feature_extraction"         # scanning resolution / feature repr
    return "unknown"


def knob_label(cfg):
    overrides = cfg.get("overrides") or {}
    if not overrides:
        return ("(baseline)" if cfg.get("model_name") == "SSG-LUGIA-F"
                else f"classifier = {cfg['model_name']}")
    return ", ".join(f"{k}={v}" for k, v in overrides.items())
