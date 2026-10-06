"""Export the landing page's interactive examples from the quickstart snippet.

Fits SMX exactly as the quickstart snippet on the landing page does (synthetic two-class spectra,
an RBF SVM, six zones) and writes, to static/assets/:

- quickstart-graph.json: the predicate graph of the first bagging repetition, as the compact JSON
  assets/graph.js reads. The layout comes from graph_data() in static/sandbox/smx_sandbox.py,
  which the Sandbox uses too.
- figures/*.html: SMX's zone-ranking, threshold-spectrum and faithfulness figures as standalone
  Plotly pages, shown in iframes. They load plotly.js from the same CDN file as the Sandbox, so
  the landing page itself carries no plotting library.

Run:  .venv/bin/pip install "spectral-model-explainer[plotting]" && .venv/bin/python scripts/export_quickstart.py
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

from smx import SMX, generate_synthetic_spectral_data, plot_threshold_spectrum

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "static" / "sandbox"))
from smx_sandbox import graph_data  # noqa: E402  (shared with the Sandbox)

ASSETS = ROOT / "static" / "assets"
CUTS = [("F1", 1, 100), ("F2", 200, 300), ("F3", 330, 430), ("F4", 500, 600), ("F5", 660, 750), ("F6", 815, 890)]
# keep in sync with PLOTLY_URL in static/sandbox/notebook.js (the plotly.js version Python's plotly uses)
PLOTLY_JS = "https://cdnjs.cloudflare.com/ajax/libs/plotly.js/4.1.1/plotly-cartesian.min.js"
# the iframe sets the size; no page margin, and the figure fills it
PAGE_STYLE = "<style>html,body{margin:0;height:100%;background:#fff}</style>"


def write_figure(fig, name: str, title: str) -> None:
    fig.update_layout(width=None, height=None, autosize=True)
    html = fig.to_html(full_html=True, include_plotlyjs=PLOTLY_JS, div_id=name, default_width="100%", default_height="100%",
                       config={"responsive": True, "displaylogo": False})
    html = html.replace("<head>", f"<head><title>{title}</title>{PAGE_STYLE}", 1)
    path = ASSETS / "figures" / f"{name}.html"
    path.parent.mkdir(exist_ok=True)
    path.write_text(html)
    print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size // 1024} KB)")


def main() -> None:
    df = generate_synthetic_spectral_data([
        {"name": "A", "n_samples": 120, "peaks": [250, 380, 550, 700, 850]},
        {"name": "B", "n_samples": 120, "peaks": [50, 250, 380, 550, 850]},
    ], n_points=500, x_min=1, x_max=1000, seed=0)
    X, y = df.drop(columns="Class"), df["Class"]
    X_cal, X_test, y_cal, y_test = (part.reset_index(drop=True) for part in train_test_split(
        X, y, test_size=0.3, stratify=y, random_state=42))
    X_mean = X_cal.mean()
    X_cal_prep, X_test_prep = X_cal - X_mean, X_test - X_mean
    model = SVC(probability=True, random_state=42).fit(X_cal_prep, y_cal)

    smx = SMX(spectral_cuts=CUTS, quantiles=[0.25, 0.5, 0.75], estimator=model,
              perturbation_metric="probability_shift")
    p_class_a = model.predict_proba(X_cal_prep)[:, 0]
    with contextlib.redirect_stdout(io.StringIO()):  # SMX reports every bag
        smx.fit(X_cal_prep, pd.Series(p_class_a), X_cal_natural=X_cal)
        faithfulness = smx.evaluate_faithfulness(X_test_prep, ranking="unique", masking_strategy="zero")

    payload = {
        "meta": {
            "dataset": "synthetic (generate_synthetic_spectral_data, seed=0)",
            "model": "SVC(probability=True, random_state=42)",
            "smx_version": version("spectral-model-explainer"),
        },
        **graph_data(smx),
    }
    out = ASSETS / "quickstart-graph.json"
    out.write_text(json.dumps(payload, separators=(",", ":")) + "\n")
    print(f"wrote {out.relative_to(ROOT)} ({len(payload['nodes'])} nodes, {len(payload['edges'])} edges)")

    write_figure(smx.plot_zone_ranking_over_spectrum(ranking="unique", X_natural=X_cal, y_labels=y_cal),
                 "zone-ranking", "Zone ranking over spectrum")
    lrc = smx.lrc_natural_.reset_index(drop=True)
    top = lrc[lrc["Zone"].notna()].index[0]  # the best-ranked predicate
    write_figure(plot_threshold_spectrum(lrc, top, smx.zones_natural_, smx.pca_info_natural_, y_cal),
                 "threshold-spectrum", f"Threshold spectrum of {lrc.loc[top, 'Node']}")
    write_figure(smx.plot_faithfulness(), "faithfulness", "Faithfulness curve")

    print(smx.lrc_summed_unique_[["Node", "Local_Reaching_Centrality"]].to_string(index=False))
    print(f"top predicate: {lrc.loc[top, 'Node_Natural']}")
    print({k: faithfulness[k] for k in ("level", "auc", "auc_normalized", "null_auc_mean", "null_percentile")})
    print(faithfulness["curve_df"].to_string())


if __name__ == "__main__":
    main()
