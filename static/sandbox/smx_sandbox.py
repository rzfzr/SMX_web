"""Helpers for the SMX Sandbox notebook.

graph_data() is also used by scripts/export_quickstart_graph.py to build the landing page's graph.
"""

from __future__ import annotations

import math

import networkx as nx
import pandas as pd

__all__ = ["graph_data"]


def _round(x: float, digits: int = 4) -> float | None:
    """Round to a few significant digits (NaN/inf -> None) to keep the JSON small."""
    x = float(x)
    if math.isnan(x) or math.isinf(x):
        return None
    return float(f"{x:.{digits}g}")


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
