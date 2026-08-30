"""
PROXAI stress-test pipeline #2 -- tabular ML preprocessing + training.

Adult / Census income dataset (datasets/census.csv). Five stages, each a single
tracked DataFrame transformation on one subscribed frame, each with exactly one
tunable knob so the stress test can change one stage at a time:

  subscribe(raw)
    -> clean + impute        knob: impute_strategy  (most_frequent | constant | drop_rows)
    -> encode categoricals   knob: encoding         (onehot | ordinal)
    -> scale numeric columns knob: scaler           (standard | minmax | robust | none)
    -> select features       knob: k_best           (int | "all")
    -> train + score         knob: classifier       (logreg | rf | gboost)

Everything is deterministic (fixed random_state, stratified split). Prints:

  [census-ml pipeline] overrides=...  n_features=N  test_accuracy=0.XXXX  test_f1=0.XXXX

Read by stress_test/census_ml_configs.py via the CENSUS_ML_CONFIG env var.
"""

import json
import os

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler, MinMaxScaler, RobustScaler, OrdinalEncoder
from sklearn.feature_selection import SelectKBest, f_classif
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.metrics import accuracy_score, f1_score

RANDOM_STATE = 0

COLUMN_NAMES = [
    "age", "workclass", "fnlwgt", "education", "education-num", "marital-status",
    "occupation", "relationship", "race", "sex", "capital-gain", "capital-loss",
    "hours-per-week", "native-country", "label",
]
CATEGORICAL = [
    "workclass", "education", "marital-status", "occupation", "relationship",
    "race", "sex", "native-country",
]
NUMERIC = [
    "age", "fnlwgt", "education-num", "capital-gain", "capital-loss", "hours-per-week",
]

DEFAULTS = {
    "impute_strategy": "most_frequent",   # clean stage
    "encoding": "onehot",                 # encode stage
    "scaler": "standard",                 # scale stage
    "k_best": "all",                      # select stage
    "classifier": "logreg",               # train stage
    "sample_frac": 0.3,                   # keep runs quick; not a stage knob
}


def _load_overrides():
    raw = os.environ.get("CENSUS_ML_CONFIG")
    if not raw:
        return {}
    return json.loads(raw).get("overrides", {})


def _make_scaler(name):
    return {
        "standard": StandardScaler(),
        "minmax": MinMaxScaler(),
        "robust": RobustScaler(),
        "none": None,
    }[name]


def _make_classifier(name):
    return {
        "logreg": LogisticRegression(max_iter=200, random_state=RANDOM_STATE),
        "rf": RandomForestClassifier(n_estimators=120, random_state=RANDOM_STATE),
        "gboost": GradientBoostingClassifier(random_state=RANDOM_STATE),
    }[name]


def run_pipeline(args, tracker) -> None:

    cfg = {**DEFAULTS, **_load_overrides()}

    # --- Stage 0: load + name + sample, then subscribe BEFORE any stage runs ---
    df = pd.read_csv(args.dataset)
    df.columns = COLUMN_NAMES
    if cfg["sample_frac"] and cfg["sample_frac"] < 1.0:
        df = df.sample(frac=cfg["sample_frac"], random_state=RANDOM_STATE).reset_index(drop=True)

    obj_cols = df.select_dtypes(include="object").columns
    df[obj_cols] = df[obj_cols].apply(lambda s: s.str.strip())
    df["label"] = (df["label"] == ">50K").astype(int)

    # stratified train/test marker kept as a column so the frame stays whole
    idx_train, idx_test = train_test_split(
        df.index, test_size=0.25, random_state=RANDOM_STATE, stratify=df["label"]
    )
    df["is_test"] = df.index.isin(idx_test)

    df = tracker.subscribe(df)
    tracker.analyze_changes(df)                       # snapshot: raw frame

    # --- STAGE: clean + impute (knob: impute_strategy) ---
    df_clean = df.copy()
    df_clean[CATEGORICAL] = df_clean[CATEGORICAL].replace("?", np.nan)
    if cfg["impute_strategy"] == "drop_rows":
        df_clean = df_clean.dropna(subset=CATEGORICAL).reset_index(drop=True)
    elif cfg["impute_strategy"] == "constant":
        df_clean[CATEGORICAL] = df_clean[CATEGORICAL].fillna("MISSING")
    else:  # most_frequent
        for c in CATEGORICAL:
            df_clean[c] = df_clean[c].fillna(df_clean[c].mode(dropna=True).iloc[0])
    tracker.analyze_changes(df_clean)

    # --- STAGE: encode categoricals (knob: encoding) ---
    if cfg["encoding"] == "ordinal":
        enc = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)
        df_enc = df_clean.copy()
        df_enc[CATEGORICAL] = enc.fit_transform(df_enc[CATEGORICAL].astype(str))
    else:  # onehot
        df_enc = pd.get_dummies(df_clean, columns=CATEGORICAL, dtype=int)
    tracker.analyze_changes(df_enc)

    # --- STAGE: scale numeric columns (knob: scaler) ---
    df_scaled = df_enc.copy()
    scaler = _make_scaler(cfg["scaler"])
    present_numeric = [c for c in NUMERIC if c in df_scaled.columns]
    if scaler is not None:
        df_scaled[present_numeric] = scaler.fit_transform(df_scaled[present_numeric])
    tracker.analyze_changes(df_scaled)

    # --- STAGE: select features (knob: k_best) ---
    feature_cols = [c for c in df_scaled.columns if c not in ("label", "is_test")]
    df_sel = df_scaled.copy()
    if cfg["k_best"] != "all":
        k = min(int(cfg["k_best"]), len(feature_cols))
        train_mask = ~df_sel["is_test"]
        selector = SelectKBest(f_classif, k=k)
        selector.fit(df_sel.loc[train_mask, feature_cols], df_sel.loc[train_mask, "label"])
        keep = set(np.array(feature_cols)[selector.get_support()])
        drop = [c for c in feature_cols if c not in keep]
        df_sel = df_sel.drop(columns=drop)
        feature_cols = [c for c in feature_cols if c in keep]
    tracker.analyze_changes(df_sel)

    # --- STAGE: train + score (knob: classifier) ---
    train_mask = ~df_sel["is_test"]
    test_mask = df_sel["is_test"]
    clf = _make_classifier(cfg["classifier"])
    clf.fit(df_sel.loc[train_mask, feature_cols], df_sel.loc[train_mask, "label"])
    df_pred = df_sel.copy()
    df_pred["pred"] = clf.predict(df_pred[feature_cols])
    tracker.analyze_changes(df_pred)

    y_true = df_pred.loc[test_mask, "label"]
    y_pred = df_pred.loc[test_mask, "pred"]
    acc = accuracy_score(y_true, y_pred)
    f1 = f1_score(y_true, y_pred)

    overrides = _load_overrides()
    print(f"[census-ml pipeline] overrides={overrides}  n_features={len(feature_cols)}  "
          f"test_accuracy={acc:.4f}  test_f1={f1:.4f}")
