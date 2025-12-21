from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from datetime import datetime
from typing import Dict, List, Tuple

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

COMMANDS = [
    # Limit compile scope to project files to avoid traversing site-packages.
    [
        sys.executable,
        "-m",
        "compileall",
        "-q",
        "app.py",
        "data_engine.py",
        "logging_utils.py",
        "alternative_data.py",
        "data_sources",
        "scripts",
        "tools",
    ],
    [sys.executable, "-c", "import app"],
    [sys.executable, "scripts/smoke_single_stock.py", "600519.SH"],
    [sys.executable, "scripts/smoke_news_bundle.py", "600519.SH"],
    [sys.executable, "scripts/smoke_data_integrity.py", "600519.SH"],
]

IMPORTS = [
    "app",
    "data_engine",
    "logging_utils",
    "alternative_data",
    "data_sources.provider_registry",
    "data_sources.quote_eastmoney",
    "data_sources.financial_eastmoney",
    "data_sources.moneyflow_eastmoney",
    "data_sources.news_announcements_eastmoney",
    "data_sources.news_reports_eastmoney",
    "data_sources.news_hot_eastmoney",
]

NETWORK_KEYWORDS = [
    "Network is unreachable",
    "Connection refused",
    "timed out",
    "Max retries",
    "Temporary failure",
    "proxy",
    "502",
    "503",
]


class CommandResult:
    def __init__(self, cmd: List[str], exit_code: int, stdout: str, stderr: str):
        self.cmd = cmd
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr

    def to_dict(self) -> Dict[str, object]:
        return {
            "cmd": " ".join(self.cmd),
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


class DoctorContext:
    def __init__(self) -> None:
        self.command_results: List[CommandResult] = []
        self.import_errors: List[Tuple[str, str]] = []
        self.smoke_metrics: List[Dict[str, object]] = []
        self.network_blocked_signals: List[str] = []
        self.file_line_refs: List[str] = []

    def record_network_signals(self, text: str) -> None:
        lower = text.lower()
        for kw in NETWORK_KEYWORDS:
            if kw.lower() in lower and kw not in self.network_blocked_signals:
                self.network_blocked_signals.append(kw)

    def record_file_line_refs(self, text: str) -> None:
        for line in text.splitlines():
            if "File \"" in line and "line" in line:
                cleaned = line.strip()
                if cleaned and cleaned not in self.file_line_refs:
                    self.file_line_refs.append(cleaned)


def run_command(cmd: List[str], timeout: int = 180) -> CommandResult:
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        stderr = (stderr or "") + f"\nTIMEOUT after {timeout}s"
        return CommandResult(cmd, 124, stdout, stderr)
    return CommandResult(cmd, proc.returncode, stdout, stderr)


def run_imports(ctx: DoctorContext) -> None:
    for mod in IMPORTS:
        try:
            __import__(mod)
        except Exception as exc:  # pragma: no cover - diagnostic path
            ctx.import_errors.append((mod, repr(exc)))


def parse_smoke_output(stdout: str) -> List[Dict[str, object]]:
    if not stdout:
        return []
    candidates: List[str] = [stdout]
    lines = stdout.splitlines()
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") or stripped.startswith("{"):
            candidates.append("\n".join(lines[idx:]))
    for candidate in reversed(candidates):
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return [data]
        except Exception:
            continue
    return []


def analyze_smoke(ctx: DoctorContext, cmd: List[str], res: CommandResult) -> None:
    entries = parse_smoke_output(res.stdout)
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        diag = entry.get("diagnostics") or entry.get("diag") or []
        if isinstance(diag, dict):
            diag = [diag]
        diag_map = {d.get("module"): d for d in diag if isinstance(d, dict)}
        for module in ["quote", "financial", "money_flow", "news_bundle"]:
            info = diag_map.get(module, {})
            filled = info.get("filled") or 0
            err_cnt = info.get("errors_count") or 0
            if filled == 0 or err_cnt > 0:
                status = "FAIL"
            else:
                status = "OK"
            ctx.smoke_metrics.append(
                {
                    "cmd": " ".join(cmd),
                    "code": entry.get("code") or entry.get("symbol"),
                    "module": module,
                    "filled": filled,
                    "errors_count": err_cnt,
                    "status": status,
                }
            )
        fail_list = entry.get("failures") if isinstance(entry.get("failures"), list) else []
        for failure in fail_list:
            ctx.smoke_metrics.append(
                {
                    "cmd": " ".join(cmd),
                    "code": entry.get("code"),
                    "module": "failure",
                    "filled": None,
                    "errors_count": None,
                    "status": failure,
                }
            )


def build_report(ctx: DoctorContext) -> str:
    lines: List[str] = []
    lines.append("# Doctor Report")
    lines.append("")
    lines.append("Generated: %s" % datetime.utcnow().isoformat() + "Z")
    lines.append("")

    lines.append("## Environment")
    lines.append(f"- Python: {sys.version}")
    lines.append(f"- Platform: {platform.platform()}")
    net = ctx.network_blocked_signals or ["none detected"]
    lines.append(f"- Network signals: {', '.join(net)}")
    lines.append("")

    lines.append("## Commands Executed")
    for res in ctx.command_results:
        lines.append(f"- `{ ' '.join(res.cmd) }` -> exit {res.exit_code}")
        snippet = (res.stdout or res.stderr).strip().splitlines()
        if snippet:
            preview = "\n".join(snippet[:10])
            lines.append("```")
            lines.append(preview)
            lines.append("```")
    lines.append("")

    lines.append("## Import Sanity")
    if ctx.import_errors:
        for mod, err in ctx.import_errors:
            lines.append(f"- ❌ {mod}: {err}")
    else:
        lines.append("- ✅ All target modules imported without exception")
    lines.append("")

    lines.append("## File/Line References")
    if ctx.file_line_refs:
        for ref in ctx.file_line_refs:
            lines.append(f"- {ref}")
    else:
        lines.append("- No file:line hints captured")
    lines.append("")

    lines.append("## Smoke Metrics")
    if ctx.smoke_metrics:
        lines.append("| Command | Code | Module | Filled | Errors | Status |")
        lines.append("|---|---|---|---|---|---|")
        for row in ctx.smoke_metrics:
            lines.append(
                f"| {row.get('cmd')} | {row.get('code') or ''} | {row.get('module')} | {row.get('filled')} | {row.get('errors_count')} | {row.get('status')} |"
            )
    else:
        lines.append("- No smoke metrics parsed (likely due to non-JSON output)")
    lines.append("")

    lines.append("## Findings Summary")
    if ctx.import_errors:
        lines.append("- Import errors present; see above for details.")
    for row in ctx.smoke_metrics:
        if row.get("module") in {"quote", "financial", "money_flow", "news_bundle"} and row.get("status") == "FAIL":
            lines.append(
                f"- {row.get('module')} unavailable for {row.get('code')} (filled={row.get('filled')}, errors={row.get('errors_count')})"
            )
        if row.get("module") == "failure":
            lines.append(f"- Smoke failure: {row.get('status')} for {row.get('code')}")
    if not ctx.import_errors and not ctx.smoke_metrics:
        lines.append("- No actionable findings captured")
    lines.append("")

    lines.append("## Data Integrity Notes")
    lines.append("- Validate that evidence_pack includes provider_trace and separated retrieved_at/report_period in downstream debugging.")
    lines.append("- If filled=0 appears alongside network errors, treat as NETWORK_BLOCKED rather than success.")
    lines.append("")

    lines.append("## Next-step Minimal Fix Plan")
    lines.append("- Harden providers to return non-empty filled_metrics or surface clearer network errors in diagnostics.")
    lines.append("- Ensure smoke scripts treat filled=0 or errors_count>0 as failures (already enforced in current scripts).")
    lines.append("- Re-run doctor_report after addressing data availability and serialization gaps.")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    ctx = DoctorContext()

    # Run imports
    run_imports(ctx)

    # Run commands
    for cmd in COMMANDS:
        res = run_command(cmd)
        ctx.command_results.append(res)
        ctx.record_network_signals(res.stdout + "\n" + res.stderr)
        ctx.record_file_line_refs(res.stdout + "\n" + res.stderr)
        if "smoke" in cmd[1]:
            analyze_smoke(ctx, cmd, res)

    report = build_report(ctx)
    report_path = os.path.join(ROOT, "DOCTOR_REPORT.md")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
