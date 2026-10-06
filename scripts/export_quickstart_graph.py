"""Export the landing page's example predicate graph to static/assets/quickstart-graph.json.

Fits SMX exactly as the quickstart snippet on the landing page does (synthetic two-class spectra,
an RBF SVM, six zones) and writes the graph of the first bagging repetition as the compact JSON
the interactive graph reads. The JSON layout comes from graph_data() in
static/sandbox/smx_sandbox.py, which the Sandbox uses too.

Run:  .venv/bin/pip install spectral-model-explainer && .venv/bin/python scripts/export_quickstart_graph.py
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
from importlib.metadata import version
from pathlib import Path

import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.svm import SVC

from smx import SMX, generate_synthetic_spectral_data

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "static" / "sandbox"))
from smx_sandbox import graph_data  # noqa: E402  (shared with the Sandbox)

OUT = ROOT / "static" / "assets" / "quickstart-graph.json"
CUTS = [("F1", 1, 100), ("F2", 200, 300), ("F3", 330, 430), ("F4", 500, 600), ("F5", 660, 750), ("F6", 815, 890)]


def main() -> None:
    df = generate_synthetic_spectral_data([
        {"name": "A", "n_samples": 120, "peaks": [250, 380, 550, 700, 850]},
        {"name": "B", "n_samples": 120, "peaks": [50, 250, 380, 550, 850]},
    ], n_points=500, x_min=1, x_max=1000, seed=0)
    X, y = df.drop(columns="Class"), df["Class"]
    X_cal, X_test, y_cal, y_test = (part.reset_index(drop=True) for part in train_test_split(
        X, y, test_size=0.3, stratify=y, random_state=42))
    X_cal_prep = X_cal - X_cal.mean()
    model = SVC(probability=True, random_state=42).fit(X_cal_prep, y_cal)

    smx = SMX(spectral_cuts=CUTS, quantiles=[0.25, 0.5, 0.75], estimator=model,
              perturbation_metric="probability_shift")
    p_class_a = model.predict_proba(X_cal_prep)[:, 0]
    with contextlib.redirect_stdout(io.StringIO()):  # SMX reports every bag
        smx.fit(X_cal_prep, pd.Series(p_class_a), X_cal_natural=X_cal)

    payload = {
        "meta": {
            "dataset": "synthetic (generate_synthetic_spectral_data, seed=0)",
            "model": "SVC(probability=True, random_state=42)",
            "smx_version": version("spectral-model-explainer"),
        },
        **graph_data(smx),
    }
    OUT.write_text(json.dumps(payload, separators=(",", ":")) + "\n")
    print(f"wrote {OUT} ({len(payload['nodes'])} nodes, {len(payload['edges'])} edges)")
    print(smx.lrc_summed_unique_[["Node", "Local_Reaching_Centrality"]].head(3).to_string(index=False))


if __name__ == "__main__":
    main()
