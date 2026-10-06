# SMX website

Website for the [Spectral Model eXplainer (SMX)](https://github.com/joseviniciusr/SMX)
(`pip install spectral-model-explainer`), published with GitHub Pages at https://rzfzr.github.io/SMX_web/.
It follows [DPG_web](https://github.com/Meta-Group/DPG_web), the site of the Decision Predicate Graph that SMX builds on.

| Path | What |
|---|---|
| `static/index.html`, `static/assets/` | Landing page: what SMX is, how it works, the interactive predicate graph, install, quickstart, links to the [docs](https://spectral-model-explainer.readthedocs.io/), citation |
| `static/sandbox/` | Sandbox: an in-browser SMX notebook (below) |
| `scripts/export_quickstart.py` | Rebuilds the landing page's interactive examples from its quickstart snippet: the predicate graph (`static/assets/quickstart-graph.json`) and SMX's zone-ranking, threshold-spectrum and faithfulness figures (`static/assets/figures/*.html`). Needs `pip install "spectral-model-explainer[plotting]"` |

`.github/workflows/pages.yml` publishes `static/` on every push to `main` that touches it
(Settings → Pages → Source: **GitHub Actions**).

To preview the site locally: `cd static && python3 -m http.server`.

The landing page's figures are SMX's own Plotly output, exported as standalone HTML pages and shown in
iframes. Each page loads plotly.js from the same cdnjs file as the Sandbox (the browser downloads it once),
so the landing page itself carries no plotting library. `assets/graph.js` draws the predicate graph with
[Cytoscape.js](https://js.cytoscape.org/), vendored in `static/assets/vendor/`.

## Sandbox

`static/sandbox/` runs SMX in the browser with [Pyodide](https://pyodide.org) (Python 3.14 and
scikit-learn compiled to WebAssembly), so it works on GitHub Pages with no server.

| File | What |
|---|---|
| `quickstart_synthetic.ipynb` | The notebook shown on the page (a real `.ipynb`), following SMX's `examples/quickstart.py`. Lines ending in `# @param {...}` become form fields and `# @markdown` lines head form sections, in the style of Google Colab. |
| `notebook.js` | Renders the cells (CodeMirror editors, Shift+Enter to run), the parameter form, CSV loading, rich outputs and `.ipynb` download. |
| `worker.js` | Python kernel: Pyodide in a module web worker. It installs the latest `spectral-model-explainer` and `plotly` from PyPI with micropip on start. |
| `smx_sandbox.py` | Display helpers (`show_dataset`, `show_metrics`, `zone_editor`, `show_graph`, `show_faithfulness`, `display`) and `graph_data()`. In the Sandbox they send JSON to the page; in Jupyter they fall back to IPython display, so a downloaded notebook runs there too. |

The notebook generates two classes of synthetic spectra with `generate_synthetic_spectral_data`; the form
sets their peaks, heights, width, noise and size. A CSV loaded from disk (one row per spectrum, spectral
columns named by their position, plus a class column) replaces them and stays in the browser. With more than
two classes SMX explains one class against the rest. The rest of the form picks the classifier, how the
spectral zones are made (detected peaks, equal width, or manual) and the SMX settings.

Manual zones can be drawn on the mean spectrum in the zones cell (`zone_editor`): drag across the chart to add a
zone, drag a zone or its edges to move it, remove zones with ×. Each edit writes the ranges into the form's
`manual_zones` and switches `zones` to manual; the next run uses them.

SMX's Plotly figures are drawn with plotly.js (the cartesian bundle from cdnjs), loaded when the first figure
appears. The first visit downloads about 60 MB (Pyodide, NumPy, pandas, SciPy, scikit-learn, matplotlib,
Plotly) from the jsDelivr CDN and PyPI, which the browser then caches; with the default settings the whole
notebook runs in about a minute. To upgrade Pyodide, change the version in the `import` at the top of
`worker.js`; when Python's Plotly moves to a new plotly.js major version, update `PLOTLY_URL` in `notebook.js`.
