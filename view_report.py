#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "textual>=1.0.0",
#   "rich>=13.0.0",
# ]
# ///

"""Interactive TUI viewer for eval reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from rich.markup import escape
from rich.syntax import Syntax
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    RichLog,
    Static,
)

METRIC_NAMES = [
    "json_schema_valid",
    "decision_match_oracle",
    "issue_categories_match_oracle",
]

METRIC_WEIGHTS: dict[str, float] = {
    "json_schema_valid": 1.0,
    "decision_match_oracle": 1.0,
    "issue_categories_match_oracle": 1.0,
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pass_rate(records: list[dict], metric: str) -> tuple[int, int]:
    """Return (passed, total) for a metric across records."""
    passed = sum(1 for r in records if r.get("metrics", {}).get(metric))
    return passed, len(records)


_SHORT_METRIC_NAMES: dict[str, str] = {
    "json_schema_valid": "schema",
    "decision_match_oracle": "decision",
    "issue_categories_match_oracle": "categories",
}


def _short_metric_name(metric: str) -> str:
    return _SHORT_METRIC_NAMES.get(metric, metric)


def _fmt_pct(n: int, total: int) -> str:
    if total == 0:
        return "—"
    return f"{100 * n / total:.1f}%"


def _fmt_evidence(evidence: list[dict] | str | None, indent: str = "       ") -> list[str]:
    """Render evidence pointers: structured field paths or doc_id + verbatim quote."""

    if not evidence:
        return []
    if isinstance(evidence, str):
        return [f"{indent}evidence: {evidence}"]
    if not isinstance(evidence, list):
        return [f"{indent}evidence: {json.dumps(evidence, ensure_ascii=False)}"]
    out: list[str] = []
    for e in evidence:
        if not isinstance(e, dict):
            out.append(f"{indent}- {e}")
            continue
        src = e.get("source", "?")
        if e.get("doc_id"):
            src = f"{e.get('doc_type') or 'document'} {e.get('date') or ''} doc_id={str(e.get('doc_id'))[:8]}…"
        line = f"{indent}- [{src}]"
        if e.get("value"):
            line += f" {e['value']}"
        if e.get("quote"):
            line += f'  "{e["quote"]}"'
        if e.get("verified") is False:
            line += "  (UNVERIFIED QUOTE)"
        out.append(line)
    return out


def _fmt_issues(issues: list[dict] | None) -> str:
    """Render issues; evidence may be a string (baseline) or a list of pointers (pipeline)."""

    if not issues:
        return "(none)"
    lines: list[str] = []
    for i, iss in enumerate(issues, 1):
        cat = iss.get("category", "?")
        desc = iss.get("summary") or iss.get("description", "")
        rule = f" {iss['rule']}" if iss.get("rule") else ""
        lines.append(f"  {i}. [{cat}]{rule} {desc}")
        lines.extend(_fmt_evidence(iss.get("evidence")))
        if iss.get("resolution"):
            lines.append(f"       resolution: {iss['resolution']}")
    return "\n".join(escape(l) for l in lines)


_STATUS_MARK = {"PASS": "[green]PASS[/green]", "FAIL": "[red]FAIL[/red]", "UNKNOWN": "[yellow]UNKNOWN[/yellow]",
                "NOT_APPLICABLE": "[dim]N/A[/dim]"}


def _fmt_checks(checks: list[dict] | None) -> str:
    """One line per rule check (including PASS) with the evidence it used."""

    if not checks:
        return "(none)"
    lines: list[str] = []
    for c in checks:
        mark = _STATUS_MARK.get(c.get("status"), c.get("status"))
        lines.append(f"  {mark} {escape(c.get('rule', ''))} {escape(c.get('name', ''))}: {escape(c.get('summary', ''))}")
        inputs = c.get("inputs") or {}
        if inputs:
            lines.append(escape(f"       inputs: {json.dumps(inputs, ensure_ascii=False, default=str)}"))
        lines.extend(escape(l) for l in _fmt_evidence(c.get("evidence")))
    return "\n".join(lines)


def _fmt_reference_dates(ref: dict | None) -> str:
    if not ref:
        return "—"
    src = ref.get("procedure_date_source") or {}
    parts = [f"procedure_date={ref.get('procedure_date')}"]
    if src:
        parts.append(f"(from {src.get('source')}" + (f' doc_id={str(src.get("doc_id"))[:8]}… "{src.get("quote")}"' if src.get("doc_id") else "") + ")")
    parts.append(f"risk={ref.get('procedure_risk')}")
    parts.append(f"review_time={ref.get('review_time')}")
    return escape(" ".join(str(p) for p in parts))


# ---------------------------------------------------------------------------
# Eval report TUI
# ---------------------------------------------------------------------------


class EvalReportApp(App):
    """Textual TUI for viewing eval_report.json."""

    CSS = """
    #header-bar {
        height: 3;
        background: $primary-background;
        padding: 0 1;
    }
    #metrics-table {
        height: auto;
        max-height: 10;
        margin: 0 1;
    }
    #main-area {
        height: 1fr;
    }
    #record-list {
        width: 48;
        border-right: solid $primary;
    }
    #detail-panes {
        width: 1fr;
        height: 1fr;
    }
    #result-pane {
        width: 1fr;
        border-right: solid $primary;
    }
    #submission-pane {
        width: 1fr;
    }
    .pane-title {
        dock: top;
        height: 1;
        background: $primary-background;
        text-style: bold;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("pagedown", "page_down", "Page down", show=True),
        Binding("pageup", "page_up", "Page up", show=True),
        Binding("f", "cycle_filter", "Filter", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    def __init__(self, report: dict[str, Any]) -> None:
        super().__init__()
        self.report = report
        self.records: list[dict] = report.get("records", [])
        self._active_filter: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield self._build_header_bar()
        yield self._build_metrics_table()
        with Horizontal(id="main-area"):
            yield self._build_record_list()
            with Horizontal(id="detail-panes"):
                with Vertical(id="result-pane"):
                    yield Static("Result", classes="pane-title")
                    yield RichLog(id="result-log", wrap=True, markup=True)
                with Vertical(id="submission-pane"):
                    yield Static("Submission", classes="pane-title")
                    yield RichLog(id="submission-log", wrap=True, markup=True)
        yield Footer()

    # -- header bar --

    def _header_text(self) -> str:
        score = self.report.get("primary_score", {}) or {}
        score_val = score.get("value_pct", "?")
        n_records = len(self.records)
        ts = self.report.get("generated_at", "")[:19]
        mode = self.report.get("mode", "eval")
        text = (
            f" Score: [bold]{score_val}%[/bold]  |  Records: {n_records}"
            f"  |  Mode: {mode}  |  Generated: {ts}"
        )
        if self._active_filter is not None:
            text += f"  |  Filter: [bold]{self._active_filter}[/bold]"
        return text

    def _build_header_bar(self) -> Static:
        return Static(self._header_text(), id="header-bar")

    # -- metrics table --

    def _build_metrics_table(self) -> DataTable:
        table = DataTable(id="metrics-table", cursor_type="row")
        table.add_columns("Metric", "Passed", "Failed", "Rate", "Weight")
        for m in METRIC_NAMES:
            passed, total = _pass_rate(self.records, m)
            failed = total - passed
            rate = _fmt_pct(passed, total)
            weight = METRIC_WEIGHTS.get(m, 1.0)
            table.add_row(m, str(passed), str(failed), rate, str(weight), key=m)
        return table

    # -- record list --

    def _build_record_list(self) -> DataTable:
        table = DataTable(id="record-list", cursor_type="row")
        table.add_columns("#", "Case", "Score", "Status")
        self._populate_record_list(table)
        return table

    def _populate_record_list(self, table: DataTable) -> None:
        sorted_records = sorted(self.records, key=lambda r: r["record_index"])
        for rec in sorted_records:
            if self._active_filter is not None:
                if rec.get("metrics", {}).get(self._active_filter):
                    continue
            idx = rec["record_index"]
            case_id = rec.get("case_id", f"#{idx}")
            score = rec.get("aggregate_local_score", 0)
            failed = [m for m in METRIC_NAMES if not rec.get("metrics", {}).get(m)]
            status = ", ".join(_short_metric_name(m) for m in failed) if failed else "✓"
            table.add_row(
                str(idx + 1),
                case_id,
                f"{score:.0f}%",
                status,
                key=str(idx),
            )

    def action_cycle_filter(self) -> None:
        # Only works when metrics table is focused
        metrics_table = self.query_one("#metrics-table", DataTable)
        if not metrics_table.has_focus:
            return

        # Get selected metric from cursor row
        row_key = metrics_table.coordinate_to_cell_key(metrics_table.cursor_coordinate).row_key
        metric = row_key.value

        # Toggle: if already filtering this metric, clear; otherwise set
        if self._active_filter == metric:
            self._active_filter = None
        else:
            self._active_filter = metric

        # Refresh record list
        record_table = self.query_one("#record-list", DataTable)
        record_table.clear()
        self._populate_record_list(record_table)

        # Update header bar
        self._update_header()

    def _update_header(self) -> None:
        self.query_one("#header-bar", Static).update(self._header_text())

    # -- detail panels --

    @on(DataTable.RowHighlighted, "#record-list")
    def _on_record_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is None:
            return
        try:
            idx = int(event.row_key.value)
        except (ValueError, TypeError):
            return
        rec = next((r for r in self.records if r["record_index"] == idx), None)
        if not rec:
            return

        # Result pane
        result_log = self.query_one("#result-log", RichLog)
        result_log.clear()
        result_log.write(self._render_detail(rec))
        result_log.scroll_home(animate=False)

        # Submission pane
        sub_log = self.query_one("#submission-log", RichLog)
        sub_log.clear()
        sub = rec.get("submission", {}) or {}
        sub_log.write(Syntax(
            json.dumps(sub, indent=2, default=str),
            "json",
            theme="monokai",
            word_wrap=True,
        ))
        sub_log.scroll_home(animate=False)

    def _render_detail(self, rec: dict) -> str:
        idx = rec["record_index"]
        case_id = rec.get("case_id", "?")
        score = rec.get("aggregate_local_score", 0)

        label = rec.get("label", {}) or {}
        actual = rec.get("parsed_output", {}) or {}
        parse_err = rec.get("parse_error")
        baseline_err = rec.get("baseline_error")
        metrics = rec.get("metrics", {})

        lines: list[str] = []
        lines.append(f"[bold]Record {idx}[/bold] — {case_id}")
        lines.append(f"Score: {score:.1f}%\n")

        # Metrics
        lines.append("[bold]Metrics:[/bold]")
        for m in METRIC_NAMES:
            v = metrics.get(m)
            mark = "[green]PASS[/green]" if v else "[red]FAIL[/red]"
            lines.append(f"  {m}: {mark}")

        if baseline_err:
            lines.append(f"\n[red]Baseline error:[/red] {baseline_err}")
        if parse_err:
            lines.append(f"\n[red]Parse error:[/red] {parse_err}")

        # Side-by-side: decision
        lines.append("\n[bold]Decision:[/bold]")
        l_dec = label.get("decision", "?")
        a_dec = actual.get("decision", "?")
        match = "✓" if l_dec == a_dec else "✗"
        lines.append(f"  Label:   {l_dec}")
        lines.append(f"  Actual:  {a_dec}  {match}")

        # Categories comparison
        lines.append("\n[bold]Label categories:[/bold]")
        lines.append("  " + (", ".join(label.get("categories") or []) or "(none)"))

        lines.append("\n[bold]Why (labeler's rationale):[/bold]")
        lines.append(f"  {escape(label.get('rationale') or '—')}")

        lines.append("\n[bold]Actual issues:[/bold]")
        lines.append(_fmt_issues(actual.get("issues")))

        lines.append("\n[bold]Decision rationale:[/bold]")
        lines.append(f"  {escape(str(actual.get('decision_rationale') or actual.get('explanation', '—')))}")

        if actual.get("reference_dates"):
            lines.append("\n[bold]Reference dates:[/bold]")
            lines.append("  " + _fmt_reference_dates(actual.get("reference_dates")))

        if actual.get("checks"):
            lines.append("\n[bold]Rule checks (audit trail, incl. PASS):[/bold]")
            lines.append(_fmt_checks(actual.get("checks")))

        if actual.get("assumptions_applied"):
            lines.append("\n[bold]Assumptions applied:[/bold] " + escape(", ".join(actual["assumptions_applied"])))

        meta = actual.get("meta")
        if meta:
            lines.append("\n[bold]Meta:[/bold] " + escape(
                f"model={meta.get('model')} pipeline={meta.get('pipeline_version')} llm_calls={meta.get('llm_calls')} "
                f"cache_hits={meta.get('llm_cache_hits')} llm_failures={meta.get('llm_failures')} "
                f"unverified_quotes={meta.get('unverified_quotes')} docs_failed={meta.get('documents_failed')}"))

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="View eval report")
    parser.add_argument(
        "--report",
        default="data/eval_report.json",
        help="Path to eval report JSON",
    )
    args = parser.parse_args()

    path = Path(args.report)
    if not path.exists():
        print(f"Report not found: {path}")
        raise SystemExit(1)

    try:
        report = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON in {path}: {exc}")
        raise SystemExit(1)

    EvalReportApp(report).run()


if __name__ == "__main__":
    main()
