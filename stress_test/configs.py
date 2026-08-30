"""
11 stress-test configurations for the SSG-LUGIA pipeline, each varying ONE
stage relative to a baseline (SSG-LUGIA-F defaults), so PROXAI's provenance
trace can be checked against a known cause for each accuracy/behavior delta.

Stages exercised:
  - Classifier variant (F / R / P)         -> anomaly detection stage
  - Window size / step ("scanning resolution") -> feature extraction stage
  - Feature representation (karlin_mode, entropy_features, pca dims) -> feature extraction stage
"""

CONFIGS = [
    # --- baseline ---
    {"name": "baseline_F",              "model_name": "SSG-LUGIA-F", "overrides": {}},

    # --- classifier variant stage (expect large swings, per prior finding) ---
    {"name": "classifier_R",            "model_name": "SSG-LUGIA-R", "overrides": {}},
    {"name": "classifier_P",            "model_name": "SSG-LUGIA-P", "overrides": {}},

    # --- window size / scanning resolution stage ---
    {"name": "window_coarse_20000",     "model_name": "SSG-LUGIA-F", "overrides": {"w": 20000, "dw": 200}},
    {"name": "window_fine_5000",        "model_name": "SSG-LUGIA-F", "overrides": {"w": 5000,  "dw": 50}},
    {"name": "window_very_fine_1000",   "model_name": "SSG-LUGIA-F", "overrides": {"w": 1000,  "dw": 10}},  # tests small-island visibility, like the "smallest targets invisible" case
    {"name": "step_dense_25",           "model_name": "SSG-LUGIA-F", "overrides": {"dw": 25}},

    # --- feature representation stage ---
    {"name": "feature_karlin_raw",      "model_name": "SSG-LUGIA-F", "overrides": {"karlin_mode": "raw"}},
    {"name": "feature_karlin_original", "model_name": "SSG-LUGIA-F", "overrides": {"karlin_mode": "original"}},
    {"name": "feature_no_entropy",      "model_name": "SSG-LUGIA-F", "overrides": {"entropy_features": False}},
    {"name": "feature_more_pca",        "model_name": "SSG-LUGIA-F", "overrides": {"pca_dn": 5, "pca_amino_acid": 5, "pca_kmer4": 5}},
]
