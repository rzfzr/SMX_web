"""Display helpers for the SMX Sandbox notebook.

Inside the Sandbox (Pyodide in a web worker) the helpers send structured results to the
page, which renders them as tables, stat tiles, Plotly figures and the interactive predicate
graph. Anywhere else, e.g. a downloaded copy of the notebook in Jupyter, they fall back to
IPython's display.

graph_data() is also used by scripts/export_quickstart_graph.py to build the landing page's graph.
"""

from __future__ import annotations

import io
import json
import math
import time
import traceback

import networkx as nx
import numpy as np
import pandas as pd

try:  # only present inside the Sandbox worker
    from sandbox_bridge import emit as _bridge_emit
except ImportError:
    _bridge_emit = None

IN_SANDBOX = _bridge_emit is not None
MAX_TABLE_ROWS = 500

__all__ = [
    "display", "graph_data", "show_dataset", "show_faithfulness", "show_graph", "show_metrics",
]


# ---------------------------------------------------------------------------
# data conversion
# ---------------------------------------------------------------------------


def _plain(value):
    """Make numpy/pandas scalars JSON-friendly (NaN/inf -> None)."""
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        value = float(value)
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if value is None or isinstance(value, (int, str, bool)):
        return value
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return str(value)


def _round(x: float, digits: int = 4) -> float | None:
    """Round to a few significant digits (NaN/inf -> None) to keep the JSON small."""
    x = float(x)
    if math.isnan(x) or math.isinf(x):
        return None
    return float(f"{x:.{digits}g}")


def _table(df: pd.DataFrame, caption: str | None = None, max_rows: int = MAX_TABLE_ROWS) -> dict:
    shown = df.head(max_rows)
    # a sorted or filtered frame keeps its old integer row numbers; show the index only when it means something
    keep_index = df.index.name is not None or not pd.api.types.is_integer_dtype(df.index)
    if keep_index:
        shown = shown.reset_index()
    return {
        "kind": "table",
        "caption": caption,
        "columns": [str(c) for c in shown.columns],
        "rows": [[_plain(v) for v in row] for row in shown.itertuples(index=False, name=None)],
        "total": int(len(df)),
    }


def _lookup(df: pd.DataFrame | None, column: str) -> dict:
    if df is None or column not in df.columns:
        return {}
    return {node: value for node, value in zip(df["Node"], df[column]) if pd.notna(value)}


def graph_data(explainer, repetition: int | None = None, class_names: dict | None = None) -> dict:
    """Compact JSON for the interactive graph (assets/graph.js) from a fitted ``smx.SMX``.

    SMX builds one predicate graph per bagging repetition (``graphs_by_seed_``); this exports one of
    them, ``repetition`` (default: the first valid one). Its terminal nodes ``Class_A`` and ``Class_B``
    stand for "continuous output >= class_threshold" and below it; ``class_names`` relabels them,
    e.g. ``{"A": "healthy", "B": "diseased"}``.
    """
    seeds = list(explainer.valid_seeds_)
    if not seeds:
        raise ValueError("The explainer has no valid repetition; call fit() first.")
    seed = seeds[0] if repetition is None else repetition
    if seed not in explainer.graphs_by_seed_:
        raise ValueError(f"No graph for repetition {seed}; valid repetitions: {seeds}")
    graph = explainer.graphs_by_seed_[seed]
    names = {"A": "A", "B": "B", **(class_names or {})}

    # LRC within this repetition's graph, as smx.compute_lrc computes it
    lrc = {}
    for node in graph.nodes:
        try:
            lrc[node] = nx.local_reaching_centrality(graph, node, weight="weight")
        except (ZeroDivisionError, nx.NetworkXError):
            lrc[node] = 0.0
    lrc_mean = _lookup(explainer.lrc_summed_, "Local_Reaching_Centrality")
    natural = _lookup(explainer.lrc_natural_, "Threshold_Natural")
    ranked = [n for n in explainer.lrc_summed_["Node"] if not str(n).startswith("Class_")]
    rank = {node: i + 1 for i, node in enumerate(ranked)}
    predicates = explainer.predicates_df_.set_index("rule")

    ids = {node: f"n{i}" for i, node in enumerate(graph.nodes)}
    nodes = []
    for node, attrs in graph.nodes(data=True):
        if attrs.get("node_type") == "terminal" or str(node).startswith("Class_"):
            label = attrs.get("class_label") or str(node).removeprefix("Class_")
            nodes.append({"id": ids[node], "label": f"Class {names.get(label, label)}", "isClass": True,
                          "lrc": _round(lrc[node])})
            continue
        row = predicates.loc[node] if node in predicates.index else None
        if isinstance(row, pd.DataFrame):  # duplicated rule strings: any row has the same zone/threshold
            row = row.iloc[0]
        nodes.append({
            "id": ids[node],
            "label": str(node),
            "isClass": False,
            "zone": str(row["zone"]) if row is not None else None,
            "op": str(row["operator"]) if row is not None else None,
            "threshold": _round(row["thresholds"]) if row is not None else None,
            "natural": _round(natural[node]) if node in natural else None,
            "lrc": _round(lrc[node]),
            "lrcMean": _round(lrc_mean[node]) if node in lrc_mean else None,
            "rank": rank.get(node),
        })
    edges = [{"source": ids[u], "target": ids[v], "weight": _round(d.get("weight", 1.0))}
             for u, v, d in graph.edges(data=True)]
    return {
        "zones": [str(z) for z in explainer.zone_scores_.columns],
        "repetition": seed,
        "repetitions": seeds,
        "nodes": nodes,
        "edges": edges,
    }


# ---------------------------------------------------------------------------
# public helpers
# ---------------------------------------------------------------------------


def _emit(payload: dict) -> None:
    _bridge_emit(json.dumps(payload, default=_plain, allow_nan=False))


def _is_plotly(obj) -> bool:
    return type(obj).__module__.startswith("plotly") and hasattr(obj, "to_plotly_json")


def _is_smx(obj) -> bool:
    return type(obj).__name__ == "SMX" and hasattr(obj, "graphs_by_seed_")


def display(*objs) -> None:
    """Show objects in the cell output: DataFrames as tables, Plotly figures, fitted SMX as its graph."""
    if not IN_SANDBOX:
        from IPython.display import display as ipy_display
        for obj in objs:
            if isinstance(obj, tuple):  # e.g. (figure, data) from return_df=True
                display(*obj)
            else:
                ipy_display(obj)
        return
    for obj in objs:
        if obj is None:
            continue
        if isinstance(obj, tuple):
            display(*obj)
        elif _is_plotly(obj):
            _emit({"kind": "plotly", "fig": json.loads(obj.to_json())})
        elif _is_smx(obj) and obj.valid_seeds_:
            show_graph(obj)
        elif isinstance(obj, pd.DataFrame):
            _emit(_table(obj))
        elif isinstance(obj, pd.Series):
            _emit(_table(obj.to_frame()))
        elif _is_figure(obj):
            _emit_figure(obj)
        else:
            _emit({"kind": "text", "text": repr(obj)})


def _class_colors(labels) -> dict:
    from smx.plotting import DEFAULT_THEME
    return DEFAULT_THEME.class_color_map([str(c) for c in labels])


def show_dataset(X: pd.DataFrame, y: pd.Series, positive=None) -> None:
    """Summarise a spectral dataset: size, spectral axis, class balance and the mean spectrum of each class."""
    axis = pd.to_numeric(pd.Index(X.columns).astype(str), errors="coerce")
    counts = y.astype(str).value_counts().sort_index()
    if positive is not None and str(positive) in counts.index:  # the explained class first
        counts = counts.reindex([str(positive), *[c for c in counts.index if c != str(positive)]])
    colors = _class_colors(counts.index)

    import plotly.graph_objects as go
    fig = go.Figure()
    for cls in counts.index:
        rows = X[y.astype(str).values == cls]
        mean, std = rows.mean().to_numpy(), rows.std().fillna(0).to_numpy()
        color = colors[cls]
        fig.add_trace(go.Scatter(x=np.r_[axis, axis[::-1]], y=np.r_[mean + std, (mean - std)[::-1]],
                                 fill="toself", fillcolor=color, opacity=0.18, line={"width": 0},
                                 hoverinfo="skip", showlegend=False))
        fig.add_trace(go.Scatter(x=axis, y=mean, name=f"{cls} (mean ± std)", line={"color": color, "width": 2}))
    fig.update_layout(template="plotly_white", height=360, margin={"l": 60, "r": 20, "t": 50, "b": 50},
                      title="Mean spectrum per class", xaxis_title="Spectral axis", yaxis_title="Intensity",
                      legend={"orientation": "h", "y": -0.2})

    if not IN_SANDBOX:
        print(f"{len(X)} spectra × {X.shape[1]} points ({axis.min():g} to {axis.max():g}), "
              f"{len(counts)} classes")
        display(counts.to_frame("spectra"), fig)
        return
    _emit({
        "kind": "dataset",
        "rows": int(len(X)),
        "points": int(X.shape[1]),
        "range": [_plain(axis.min()), _plain(axis.max())],
        "classes": {str(k): int(v) for k, v in counts.items()},
        "colors": colors,
        "positive": None if positive is None else str(positive),
    })
    display(fig)


def show_metrics(metrics: dict) -> None:
    """Show named scores ({name: value}) as stat tiles."""
    if not IN_SANDBOX:
        display(pd.Series(metrics, name="score").to_frame())
        return
    _emit({"kind": "metrics", "metrics": {str(k): float(v) for k, v in metrics.items()}})


def show_graph(explainer, repetition: int | None = None, class_names: dict | None = None) -> None:
    """Render one repetition's predicate graph of a fitted SMX explainer as the interactive graph."""
    data = graph_data(explainer, repetition, class_names)
    if not IN_SANDBOX:
        labels = {n["id"]: n["label"] for n in data["nodes"]}
        edges = pd.DataFrame([(labels[e["source"]], labels[e["target"]], e["weight"]) for e in data["edges"]],
                             columns=["from", "to", "weight"]).sort_values("weight", ascending=False)
        print(f"Predicate graph of repetition {data['repetition']}: {len(data['nodes'])} nodes, "
              f"{len(edges)} edges (the interactive graph needs the Sandbox); strongest edges:")
        display(edges.head(15).reset_index(drop=True))
        return
    _emit({"kind": "graph", "data": data})


def show_faithfulness(result: dict) -> None:
    """Summarise smx.SMX.evaluate_faithfulness(): level, AUC and how it compares with random rankings."""
    summary = {
        "level": result.get("level"),
        "auc": result.get("auc"),
        "aucNormalized": result.get("auc_normalized"),
        "percentile": result.get("null_percentile"),
        "nullMean": result.get("null_auc_mean"),
        "nullStd": result.get("null_auc_std"),
        "zones": result.get("n_masked_zones"),
        "metric": result.get("metric"),
    }
    if not IN_SANDBOX:
        display(pd.Series(summary, name="faithfulness").to_frame())
        return
    _emit({"kind": "faithfulness", **{k: _plain(v) for k, v in summary.items()}})


# ---------------------------------------------------------------------------
# matplotlib: show figures inline, like Jupyter's inline backend
# ---------------------------------------------------------------------------


def _is_figure(obj) -> bool:
    return type(obj).__name__ == "Figure" and hasattr(obj, "savefig")


def _emit_figure(fig) -> None:
    import base64
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    _emit({"kind": "image", "png": base64.b64encode(buf.getvalue()).decode("ascii")})


def _flush_figures() -> None:
    import sys
    if "matplotlib.pyplot" not in sys.modules:
        return
    import matplotlib.pyplot as plt
    for num in plt.get_fignums():
        _emit_figure(plt.figure(num))
    plt.close("all")


# ---------------------------------------------------------------------------
# cell execution (Sandbox only; called by worker.js)
# ---------------------------------------------------------------------------


class _Stream(io.TextIOBase):
    """stdout/stderr that forwards text to the page, batched so progress output stays cheap."""

    def __init__(self, name: str):
        self.name, self._buf, self._last = name, [], 0.0

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        self._buf.append(text)
        if time.monotonic() - self._last > 0.1:
            self.flush()
        return len(text)

    def flush(self) -> None:
        if self._buf:
            _emit({"kind": "stream", "name": self.name, "text": "".join(self._buf)})
            self._buf = []
        self._last = time.monotonic()


_namespace: dict = {"__name__": "__main__"}


def _setup() -> None:
    import matplotlib
    matplotlib.use("agg")
    import matplotlib.pyplot as plt
    plt.show = lambda *args, **kwargs: _flush_figures()
    # fig.show() renders in the cell output, as in Jupyter
    from plotly.basedatatypes import BaseFigure
    BaseFigure.show = lambda self, *args, **kwargs: display(self)


async def run_cell(code: str, count: int) -> bool:
    """Run one notebook cell; the value of a trailing expression is displayed, as in Jupyter."""
    import contextlib
    import linecache

    from pyodide.code import eval_code_async

    filename = f"<cell {count}>"
    linecache.cache[filename] = (len(code), None, code.splitlines(True), filename)  # source lines in tracebacks
    out, err = _Stream("stdout"), _Stream("stderr")
    ok = True
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            result = await eval_code_async(code, globals=_namespace, return_mode="last_expr", filename=filename)
            out.flush(); err.flush()
            if result is not None:
                display(result)
            _flush_figures()
        except BaseException as exc:  # noqa: BLE001 - report everything, like Jupyter
            ok = False
            out.flush(); err.flush()
            frames = traceback.extract_tb(exc.__traceback__)
            # drop the frames of this runner and of Pyodide's eval machinery
            start = next((i for i, f in enumerate(frames) if f.filename.startswith("<cell")), 0)
            lines = traceback.format_list(frames[start:]) if frames else []
            _emit({
                "kind": "error",
                "ename": type(exc).__name__,
                "evalue": str(exc),
                "traceback": "".join(lines),
            })
    out.flush(); err.flush()
    return ok
