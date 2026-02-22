"""
dynamo_backend.debug_panel
~~~~~~~~~~~~~~~~~~~~~~~~~~
A Django Debug Toolbar panel that records every DynamoDB call made during
a request and displays a table of operations, timings, and parameters.

The compiler's I/O helpers call ``record_ddb_call()`` after each operation.
This module is a no-op when debug_toolbar is not installed or DEBUG=False.

Panel registration in settings.py::

    DEBUG_TOOLBAR_PANELS = [
        "dynamo_backend.debug_panel.DynamoPanel",
        "debug_toolbar.panels.history.HistoryPanel",
        "debug_toolbar.panels.versions.VersionsPanel",
        "debug_toolbar.panels.timer.TimerPanel",
        "debug_toolbar.panels.settings.SettingsPanel",
        "debug_toolbar.panels.headers.HeadersPanel",
        "debug_toolbar.panels.request.RequestPanel",
        "debug_toolbar.panels.templates.TemplatesPanel",
        "debug_toolbar.panels.alerts.AlertsPanel",
        "debug_toolbar.panels.staticfiles.StaticFilesPanel",
        "debug_toolbar.panels.logging.LoggingPanel",
        "debug_toolbar.panels.redirects.RedirectsPanel",
        "debug_toolbar.panels.profiling.ProfilingPanel",
    ]
"""

from __future__ import annotations

import html
import json
import threading
from typing import Any

# ── Thread-local per-request query store ──────────────────────────────────────

_local = threading.local()

OP_BADGE_COLOUR = {
    "GET_ITEM":   "#2196F3",   # blue
    "BATCH_GET":  "#9C27B0",   # purple
    "GSI_QUERY":  "#4CAF50",   # green
    "SCAN":       "#FF9800",   # orange  ← potentially slow
    "PUT_ITEM":   "#009688",   # teal
    "DELETE":     "#F44336",   # red
    "UPDATE":     "#795548",   # brown
}


def reset_ddb_queries() -> None:
    """Clear the per-thread query log and FK cache (called at the start of each request)."""
    _local.queries = []
    _local.fk_cache = {}


# ── Per-request FK lookup cache ────────────────────────────────────────────────
# Keyed by (table_name, pk_value_str) → DynamoDB item dict (or None if not found).
# Lives for the duration of one request; reset by reset_ddb_queries() above and
# also by DynamoCacheMiddleware for requests that don't use the debug panel.

def reset_request_cache() -> None:
    """Reset only the FK cache (called by DynamoCacheMiddleware on every request)."""
    _local.fk_cache = {}


def get_fk_cache() -> dict:
    """Return the thread-local FK cache, initialising it if needed."""
    if not hasattr(_local, "fk_cache"):
        _local.fk_cache = {}
    return _local.fk_cache


def record_ddb_call(
    op: str,
    table: str,
    duration_ms: float,
    result_count: int,
    **details: Any,
) -> None:
    """
    Append one DynamoDB operation to the thread-local log.

    Called by every I/O helper in compiler.py.
    Silent no-op when _local.queries has not been initialised
    (i.e. outside a debug-toolbar request).
    """
    store = getattr(_local, "queries", None)
    if store is None:
        return
    params = details.pop("params", None)
    # JSON-roundtrip params so only plain Python primitives are stored.
    # This prevents RecursionError in copy.deepcopy when the debug toolbar's
    # HistoryPanel deepcopies panel state — boto3 condition objects, Decimals,
    # and large Key/Item lists all become safe string/dict/list structures.
    if params is not None:
        try:
            import json
            params = json.loads(json.dumps(params, default=str))
        except Exception:
            params = {"_raw": str(params)[:500]}
    store.append(
        {
            "op": op,
            "table": table,
            "duration_ms": round(duration_ms, 2),
            "result_count": result_count,
            "details": {k: v for k, v in details.items() if v is not None},
            "params": params,
        }
    )


def get_ddb_queries() -> list[dict]:
    return list(getattr(_local, "queries", []))


# ── Debug Toolbar Panel ────────────────────────────────────────────────────────

try:
    from debug_toolbar.panels import Panel  # type: ignore

    class DynamoPanel(Panel):
        """Django Debug Toolbar panel for DynamoDB operations."""

        title = "DynamoDB"
        nav_title = "DynamoDB"

        # ── Panel lifecycle ────────────────────────────────────────────────

        def process_request(self, request):
            """Reset query log at the start of each request."""
            reset_ddb_queries()
            return super().process_request(request)

        def generate_stats(self, request, response):
            queries = get_ddb_queries()
            total_ms = sum(q["duration_ms"] for q in queries)
            scans = sum(1 for q in queries if q["op"] == "SCAN")
            self.record_stats(
                {
                    "queries": queries,
                    "total_count": len(queries),
                    "total_ms": round(total_ms, 2),
                    "scan_count": scans,
                }
            )

        # ── Nav bar subtitle ───────────────────────────────────────────────

        @property
        def nav_subtitle(self) -> str:
            stats = self.get_stats()
            if not stats:
                return ""
            n = stats.get("total_count", 0)
            ms = stats.get("total_ms", 0)
            scans = stats.get("scan_count", 0)
            label = f"{n} call{'s' if n != 1 else ''} in {ms:.1f} ms"
            if scans:
                label += f" ⚠ {scans} scan{'s' if scans != 1 else ''}"
            return label

        # ── Panel body ─────────────────────────────────────────────────────

        @property
        def content(self) -> str:
            stats = self.get_stats() or {}
            queries: list[dict] = stats.get("queries", [])
            total_ms: float = stats.get("total_ms", 0)
            scan_count: int = stats.get("scan_count", 0)

            rows_html = self._render_rows(queries)
            warning = ""
            if scan_count:
                warning = (
                    f'<p style="color:#b71c1c;font-weight:600;margin:8px 0">'
                    f"⚠ {scan_count} full-table SCAN operation{'s' if scan_count > 1 else ''} — "
                    "consider adding a GSI or narrowing the filter.</p>"
                )

            return f"""
<style>
  .ddb-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.875rem;
    font-family: monospace;
  }}
  .ddb-table th {{
    background: #f5f5f5;
    text-align: left;
    padding: 6px 10px;
    border-bottom: 2px solid #ddd;
    white-space: nowrap;
  }}
  .ddb-table td {{
    padding: 5px 10px;
    border-bottom: 1px solid #eee;
    vertical-align: top;
  }}
  .ddb-table tr:hover td {{ background: #fafafa; }}
  .ddb-badge {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 3px;
    color: #fff;
    font-size: 0.8rem;
    font-weight: 600;
    white-space: nowrap;
  }}
  .ddb-details {{ color: #444; line-height: 1.6; }}
  .ddb-details b {{ color: #222; }}
  .ddb-slow {{ background: #fff3e0; }}
</style>

<h3 style="margin: 10px 0 4px">
  DynamoDB — {len(queries)} call{'s' if len(queries) != 1 else ''}, {total_ms:.1f} ms total
</h3>
{warning}
<table class="ddb-table">
  <thead>
    <tr>
      <th>#</th>
      <th>Operation</th>
      <th>Table</th>
      <th>ms</th>
      <th>Rows</th>
      <th>Details</th>
    </tr>
  </thead>
  <tbody>
    {rows_html}
  </tbody>
</table>"""

        # ── Helpers ────────────────────────────────────────────────────────

        @staticmethod
        def _render_rows(queries: list[dict]) -> str:
            if not queries:
                return '<tr><td colspan="6" style="color:#888;padding:12px">No DynamoDB calls recorded.</td></tr>'

            rows = []
            for i, q in enumerate(queries, 1):
                op = q["op"]
                colour = OP_BADGE_COLOUR.get(op, "#607D8B")
                badge = (
                    f'<span class="ddb-badge" style="background:{colour}">{op}</span>'
                )
                details_parts = []
                for k, v in q["details"].items():
                    v_str = html.escape(str(v))
                    details_parts.append(f"<b>{k}:</b> {v_str}")
                # Raw params toggle
                raw_params = q.get("params")
                if raw_params:
                    try:
                        params_json = html.escape(json.dumps(raw_params, default=str, indent=2))
                        params_toggle = (
                            '<details style="margin-top:5px">'
                            '<summary style="cursor:pointer;color:#1565C0;font-size:0.78rem;'
                            'user-select:none;list-style:none">'
                            '&#9654; raw params</summary>'
                            f'<pre style="margin:4px 0;padding:6px 8px;background:#f4f4f8;'
                            f'border:1px solid #ccc;border-radius:3px;font-size:0.72rem;'
                            f'overflow:auto;max-height:180px;white-space:pre">'
                            f'{params_json}</pre>'
                            '</details>'
                        )
                    except Exception:
                        params_toggle = ""
                else:
                    params_toggle = ""
                details_html = "<br>".join(details_parts) + params_toggle

                slow_cls = " ddb-slow" if op == "SCAN" else ""
                rows.append(
                    f'<tr class="{slow_cls}">'
                    f"<td>{i}</td>"
                    f"<td>{badge}</td>"
                    f"<td><code>{html.escape(q['table'])}</code></td>"
                    f"<td>{q['duration_ms']:.1f}</td>"
                    f"<td>{q['result_count']}</td>"
                    f'<td class="ddb-details">{details_html}</td>'
                    f"</tr>"
                )
            return "\n".join(rows)

except ImportError:
    # django-debug-toolbar is not installed — provide a harmless stub
    class DynamoPanel:  # type: ignore[no-redef]
        pass
