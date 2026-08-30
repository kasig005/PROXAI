"""
Stress-test profile #2: tabular ML preprocessing + training on the Census /
Adult income dataset. See pipelines/census_ml_pipeline.py for the stages.

Dataset: datasets/census.csv  (already in the repo)
"""

PIPELINE_FILE = "pipelines/census_ml_pipeline.py"
CONFIG_ENV = "CENSUS_ML_CONFIG"
SUMMARY_PREFIX = "[census-ml pipeline]"
METRIC_KEYS = ["n_features", "test_accuracy", "test_f1"]
BASELINE = "baseline"


def config_payload(cfg):
    return {"overrides": cfg.get("overrides", {})}


CONFIGS = [
    {"name": "baseline",          "overrides": {}},

    # clean / impute stage
    {"name": "impute_constant",   "overrides": {"impute_strategy": "constant"}},
    {"name": "impute_drop_rows",  "overrides": {"impute_strategy": "drop_rows"}},

    # encode stage
    {"name": "encode_ordinal",    "overrides": {"encoding": "ordinal"}},

    # scale stage
    {"name": "scaler_minmax",     "overrides": {"scaler": "minmax"}},
    {"name": "scaler_robust",     "overrides": {"scaler": "robust"}},
    {"name": "scaler_none",       "overrides": {"scaler": "none"}},

    # select stage
    {"name": "select_k10",        "overrides": {"k_best": 10}},
    {"name": "select_k5",         "overrides": {"k_best": 5}},

    # train stage
    {"name": "clf_rf",            "overrides": {"classifier": "rf"}},
    {"name": "clf_gboost",        "overrides": {"classifier": "gboost"}},
]

# --- activity -> stage mapping --------------------------------------------------
STAGES = ["train", "select", "scale", "encode", "clean"]

STAGE_CODE_KEYWORDS = {
    "train": [
        "clf.fit", "clf.predict", "df_pred", "\"pred\"", "'pred'",
        "logisticregression", "randomforest", "gradientboosting",
    ],
    "select": [
        "selectkbest", "f_classif", "df_sel", "get_support", "drop(columns=drop",
        "feature_cols",
    ],
    "scale": [
        "standardscaler", "minmaxscaler", "robustscaler", "df_scaled",
        "scaler.fit_transform", "_make_scaler",
    ],
    "encode": [
        "get_dummies", "ordinalencoder", "df_enc", "categorical]",
        "fit_transform(df_enc",
    ],
    "clean": [
        "df_clean", "fillna", "dropna", "replace(\"?\"", "replace('?'", "mode(",
        "impute",
    ],
}

STAGE_LABEL = {
    "clean": "clean / impute",
    "encode": "encode categoricals",
    "scale": "scale numerics",
    "select": "feature selection",
    "train": "train + score",
    "other": "(unclassified)",
    "baseline": "baseline",
    "unknown": "unknown",
}

STAGE_NAME_KEYWORDS = {
    "train": ["train", "fit", "predict", "classif", "model", "logistic",
              "random forest", "gradient boost"],
    "select": ["select", "k best", "kbest", "feature selection", "drop"],
    "scale": ["scale", "scaling", "standard", "minmax", "min-max", "robust", "normali"],
    "encode": ["encode", "encoding", "one-hot", "onehot", "dummies", "ordinal",
               "categorical"],
    "clean": ["clean", "impute", "imputation", "missing", "fillna", "dropna",
              "median", "mode", "strip"],
}

_KNOB_STAGE = {
    "impute_strategy": "clean",
    "encoding": "encode",
    "scaler": "scale",
    "k_best": "select",
    "classifier": "train",
}


def expected_stage(cfg):
    overrides = cfg.get("overrides") or {}
    if not overrides:
        return "baseline"
    stages = {_KNOB_STAGE[k] for k in overrides if k in _KNOB_STAGE}
    return stages.pop() if len(stages) == 1 else "unknown"


def knob_label(cfg):
    overrides = cfg.get("overrides") or {}
    if not overrides:
        return "(baseline)"
    return ", ".join(f"{k}={v}" for k, v in overrides.items())
