"""
PROXAI test-case pipeline: SSG-LUGIA genomic island prediction.

SSG-LUGIA (external/SSG-LUGIA) does NOT operate on pandas DataFrames -- it runs a
genome string through: windowing -> feature extraction -> anomaly detection ->
post-processing, producing numpy arrays at each stage. This pipeline adapts each
stage onto ONE pandas DataFrame (one row per genome window) so PROXAI's
ProvenanceTracker can diff it between stages.

Key design point (v2): the DataFrame is subscribed to the tracker BEFORE feature
extraction -- it starts as just the window coordinates -- and every stage,
feature extraction included, is a tracked column-adding transformation on it:

  subscribe(windows)               # window_index, start, end
    -> +feat_* columns             # STAGE: feature extraction  (karlin/entropy/pca knobs)
    -> +anomaly_pred/score         # STAGE: anomaly detection   (classifier F/R/P)
    -> +score_median_filtered/...  # STAGE: post-processing
    -> +in_predicted_island        # STAGE: genomic islands

v1 subscribed AFTER feature extraction, so PROXAI structurally could not see the
feature-representation configs change anything. This version fixes that.

It calls SSG-LUGIA's individual stage functions directly (not the SSG_LUGIA()
wrapper in main.py) so each stage is independently observable.
"""

import sys
import os
import numpy as np
import pandas as pd

def _find_ssg_lugia_codes():
    """
    Locate external/SSG-LUGIA/codes independently of where this file lives.
    prolit_run.py runs this pipeline as a copy at the repo root (extracted_code.py)
    in --use_manual_code mode, so a path relative to __file__ can't be assumed.
    """
    rel = os.path.join("external", "SSG-LUGIA", "codes")
    here = os.path.dirname(os.path.abspath(__file__))
    for base in (here, os.path.dirname(here), os.getcwd()):
        cand = os.path.join(base, rel)
        if os.path.isdir(cand):
            return cand
    raise RuntimeError(f"Could not locate {rel} (looked near {here} and {os.getcwd()})")

SSG_LUGIA_CODES = _find_ssg_lugia_codes()
sys.path.insert(0, SSG_LUGIA_CODES)

from file_handling import loadGenome
from models import loadModel
from feature_extraction import extractFeatures
from anomaly_detection import detectAnomalies
from post_processing import medianFiltering, binaizeFilteredDistance, inferLabel, trimRegions
import json

# SSG-LUGIA's codes/utils.py collides with PROXAI's root utils.py, which
# tracking/column_entity_approach.py has already loaded into sys.modules['utils']
# by the time this pipeline runs. Load the SSG-LUGIA one by file path instead.
import importlib.util as _ilu
_ssg_utils_spec = _ilu.spec_from_file_location(
    "ssg_lugia_utils", os.path.join(SSG_LUGIA_CODES, "utils.py")
)
_ssg_utils = _ilu.module_from_spec(_ssg_utils_spec)
_ssg_utils_spec.loader.exec_module(_ssg_utils)
getGenomicIslands = _ssg_utils.getGenomicIslands

DEFAULT_MODEL_NAME = "SSG-LUGIA-F"


def _load_config():
    """
    Config resolution order:
      1. SSG_LUGIA_CONFIG env var containing a JSON object, e.g.
         '{"model_name": "SSG-LUGIA-R"}' or
         '{"model_name": "SSG-LUGIA-F", "overrides": {"w": 5000, "dw": 50}}'
      2. Falls back to DEFAULT_MODEL_NAME with no overrides.
    This lets a stress-test driver run this same pipeline file many times,
    each time with a different stage-by-stage configuration, without editing
    the file between runs.
    """
    raw = __import__("os").environ.get("SSG_LUGIA_CONFIG")
    if not raw:
        return DEFAULT_MODEL_NAME, {}
    cfg = json.loads(raw)
    return cfg.get("model_name", DEFAULT_MODEL_NAME), cfg.get("overrides", {})


def _window_starts(genome_len, w, dw):
    """Replicate extractFeatures()'s windowing loop exactly, so the DataFrame
    row count matches the feature-matrix row count."""
    starts = []
    for st in range(0, genome_len, dw):
        if st + w >= genome_len:
            break
        starts.append(st)
    return starts


def run_pipeline(args, tracker) -> None:

    # --- Stage 0: load genome + resolve model config ---
    genome = loadGenome(args.dataset)
    model_name, overrides = _load_config()
    model = dict(loadModel(model_name))   # copy so overrides don't mutate the preset
    model.update(overrides)

    L = len(genome)
    starts = _window_starts(L, model["w"], model["dw"])

    # --- Subscribe to the raw window frame BEFORE feature extraction ---
    df = pd.DataFrame({
        "window_index": range(len(starts)),
        "start": starts,
        "end": [s + model["w"] for s in starts],
    })
    df = tracker.subscribe(df)
    tracker.analyze_changes(df)                      # snapshot: raw windows

    # --- STAGE: feature extraction (karlin_mode / entropy_features / pca_* act here) ---
    X = extractFeatures(genome, model)               # 2d array: windows x features
    if len(X) != len(starts):
        raise RuntimeError(
            f"feature matrix rows ({len(X)}) != window count ({len(starts)}); "
            f"windowing replication is out of sync with extractFeatures()"
        )
    df_features = df.copy()
    for i in range(X.shape[1]):
        df_features[f"feat_{i}"] = X[:, i]
    tracker.analyze_changes(df_features)

    # --- STAGE: anomaly detection (classifier variant F / R / P acts here) ---
    yp, ys = detectAnomalies(X, model)
    df_anomaly = df_features.copy()
    df_anomaly["anomaly_pred"] = yp
    df_anomaly["anomaly_score"] = ys
    tracker.analyze_changes(df_anomaly)

    # --- STAGE: post-processing (per-window median filter + binarization) ---
    ys_mf = medianFiltering(ys, model)
    yp_mf = binaizeFilteredDistance(ys_mf)
    df_postproc = df_anomaly.copy()
    df_postproc["score_median_filtered"] = ys_mf
    df_postproc["pred_binarized"] = yp_mf
    tracker.analyze_changes(df_postproc)

    # --- STAGE: genomic islands, mapped back onto the windows ---
    per_base_label = trimRegions(inferLabel(yp_mf, L, model), model)   # (L, 1) array
    islands = getGenomicIslands(per_base_label)                        # [(start, end), ...]
    df_islands = df_postproc.copy()
    df_islands["in_predicted_island"] = [
        any(not (e < i_st or s > i_en) for i_st, i_en in islands)
        for s, e in zip(df_islands["start"], df_islands["end"])
    ]
    tracker.analyze_changes(df_islands)

    print(f"[SSG-LUGIA pipeline] model={model_name}  overrides={overrides}  "
          f"windows={len(starts)}  islands_found={len(islands)}")
