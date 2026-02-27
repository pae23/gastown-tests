#!/usr/bin/env python3
"""run_full.py — Full Gastown test cycle with OpenTelemetry observability.

Phases:
  1. Reset OpenTelemetry (docker volumes)
  2. Reset Gastown (stop Mayor)
  3. Start OTEL stack + gastown-trace
  4. Start Mayor
  5. Launch test suite (PROMPT1.md → Mayor via gt nudge)
  6. Wait for convoy to land (poll)
  7. Collect OTEL metrics + logs
  8. Generate recommendations

All output goes to reports/TIMESTAMP/*.md
Symlink reports/latest → reports/TIMESTAMP is kept up to date.

Architecture note:
  Gastown has a single global town rooted at ~/gt/.
  gt mayor start always operates in that global context.
  gt init initialises a *rig* (git repo for agents to work on), not a town.
  All gt commands are run from TOWN_DIR (~/gt/) to ensure correct routing.
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── Config ────────────────────────────────────────────────────────────────────

SCRIPT_DIR  = Path(__file__).parent.resolve()
TIMESTAMP   = datetime.now().strftime("%Y%m%d-%H%M%S")
REPORTS_DIR = SCRIPT_DIR / "reports" / TIMESTAMP
TOWN_DIR    = Path.home() / "gt"   # global gastown town root
PROMPT_FILE = SCRIPT_DIR / "PROMPT1.md"

OTEL_DIR        = Path(os.environ.get("GASTOWN_OTEL_DIR", Path.home() / "dev" / "third-party" / "gastown-otel"))
COMPOSE_FILE    = OTEL_DIR / "docker-compose.yml"
COMPOSE_PROJECT = "gastown-otel"
TRACE_BIN       = OTEL_DIR / "gastown-trace" / "gastown-trace"

VM_URL      = "http://localhost:8428"
VL_URL      = "http://localhost:9428"
GRAFANA_URL = "http://localhost:9429"
TRACE_PORT  = 7428
TRACE_URL   = f"http://localhost:{TRACE_PORT}"

CONVOY_TIMEOUT = int(os.environ.get("CONVOY_TIMEOUT", "3600"))
CONVOY_POLL    = 30

# OTEL environment variables injected into every gt/bd command.
OTEL_VARS: dict[str, str] = {
    "GT_OTEL_METRICS_URL":                  f"{VM_URL}/opentelemetry/api/v1/push",
    "GT_OTEL_LOGS_URL":                     f"{VL_URL}/insert/opentelemetry/v1/logs",
    "BD_OTEL_METRICS_URL":                  f"{VM_URL}/opentelemetry/api/v1/push",
    "BD_OTEL_LOGS_URL":                     f"{VL_URL}/insert/opentelemetry/v1/logs",
    "CLAUDE_CODE_ENABLE_TELEMETRY":         "1",
    "OTEL_METRICS_EXPORTER":                "otlp",
    "OTEL_METRIC_EXPORT_INTERVAL":          "1000",
    "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT":  f"{VM_URL}/opentelemetry/api/v1/push",
    "OTEL_EXPORTER_OTLP_METRICS_PROTOCOL":  "http/protobuf",
    "OTEL_LOGS_EXPORTER":                   "otlp",
    "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT":     f"{VL_URL}/insert/opentelemetry/v1/logs",
    "OTEL_EXPORTER_OTLP_LOGS_PROTOCOL":     "http/protobuf",
    "OTEL_LOG_TOOL_DETAILS":                "true",
    "OTEL_LOG_TOOL_CONTENT":                "true",
    "OTEL_LOG_USER_PROMPTS":                "true",
}

GT_ENV = {**os.environ, **OTEL_VARS}

# ── Logging ────────────────────────────────────────────────────────────────────

def ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

_log_file: Optional[Path] = None

def log(msg: str) -> None:
    line = f"[{ts()}] {msg}"
    print(line, flush=True)
    if _log_file:
        with _log_file.open("a") as f:
            f.write(line + "\n")

def section(name: str) -> None:
    log(f"══ {name}")
    bar = "═" * 52
    print(f"\n{bar}\n  {name}\n{bar}\n", flush=True)

# ── Report writer ─────────────────────────────────────────────────────────────

class Report:
    """Thin wrapper for writing a structured Markdown report file."""

    def __init__(self, path: Path, title: str) -> None:
        self.path = path
        self._f = path.open("w")
        self.write(f"# {title}\n\n> Started: {ts()}\n\n")

    def write(self, text: str) -> "Report":
        self._f.write(text)
        self._f.flush()
        return self

    def h2(self, text: str) -> "Report":
        return self.write(f"\n## {text}\n\n")

    def h3(self, text: str) -> "Report":
        return self.write(f"\n### {text}\n\n")

    def p(self, *lines: str) -> "Report":
        return self.write("\n".join(lines) + "\n\n")

    def blockquote(self, text: str) -> "Report":
        return self.write(f"> {text}\n\n")

    def code(self, content: str, lang: str = "") -> "Report":
        return self.write(f"```{lang}\n{content.rstrip()}\n```\n\n")

    def cmd(self, cmd_str: str, output: str) -> "Report":
        return self.code(f"$ {cmd_str}\n{output.rstrip()}")

    def table(self, headers: list[str], rows: list[list]) -> "Report":
        widths = [max(len(str(h)), max((len(str(r[i])) for r in rows), default=0))
                  for i, h in enumerate(headers)]
        def row_str(cells):
            return "| " + " | ".join(str(c).ljust(w) for c, w in zip(cells, widths)) + " |"
        sep = "|" + "|".join("-" * (w + 2) for w in widths) + "|"
        self.write(row_str(headers) + "\n" + sep + "\n")
        for row in rows:
            self.write(row_str(row) + "\n")
        return self.write("\n")

    def status(self, ok: bool, msg: str = "") -> "Report":
        icon = "✓" if ok else "⚠"
        label = msg or ("OK" if ok else "FAILED")
        return self.write(f"> {icon} **{label}** — {ts()}\n\n")

    def close(self, ok: bool = True) -> None:
        self.status(ok, "Completed" if ok else "Phase failed — see details above")
        self._f.close()

    def __enter__(self) -> "Report":
        return self

    def __exit__(self, exc_type, *_) -> None:
        self.close(ok=exc_type is None)

# ── Shell helpers ─────────────────────────────────────────────────────────────

def run_cmd(
    cmd: list[str],
    cwd: Optional[Path] = None,
    env: Optional[dict] = None,
    stdin_text: Optional[str] = None,
) -> tuple[int, str]:
    """Run a command, return (returncode, combined stdout+stderr)."""
    result = subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        input=stdin_text,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return result.returncode, result.stdout or ""


def run_compose(args: list[str]) -> tuple[int, str]:
    return run_cmd(["docker", "compose", "-f", str(COMPOSE_FILE)] + args)


def run_gt(args: list[str], stdin_text: Optional[str] = None) -> tuple[int, str]:
    """Run a gt command from the global town root with OTEL environment."""
    return run_cmd(["gt"] + args, cwd=TOWN_DIR, env=GT_ENV, stdin_text=stdin_text)


def wait_for_http(url: str, label: str, retries: int = 30, delay: int = 2) -> bool:
    log(f"Waiting for {label} ({url})…")
    for i in range(retries):
        try:
            urllib.request.urlopen(url, timeout=3)
            log(f"{label} ready")
            return True
        except Exception:
            time.sleep(delay)
    log(f"WARNING: {label} not ready after {retries * delay}s")
    return False

# ── OTEL query helpers ────────────────────────────────────────────────────────

def http_get(url: str, params: Optional[dict] = None) -> Optional[str]:
    full = url + ("?" + urllib.parse.urlencode(params) if params else "")
    try:
        with urllib.request.urlopen(full, timeout=10) as resp:
            return resp.read().decode()
    except Exception:
        return None


def vm_query(q: str) -> str:
    """Instant PromQL query → formatted string."""
    body = http_get(f"{VM_URL}/api/v1/query", {"query": q})
    if not body:
        return "  (no data)"
    try:
        results = json.loads(body).get("data", {}).get("result", [])
        if not results:
            return "  (no data)"
        lines = []
        for r in results:
            m = dict(r.get("metric", {}))
            val = r.get("value", [None, "n/a"])[1]
            name = m.pop("__name__", q)
            labels = ", ".join(f"{k}={v}" for k, v in m.items())
            suffix = f"{{{labels}}}" if labels else ""
            lines.append(f"  {name}{suffix} = {val}")
        return "\n".join(lines)
    except Exception as e:
        return f"  (parse error: {e})"


def vm_scalar(q: str) -> float:
    """Return a single numeric value from VictoriaMetrics, or 0."""
    body = http_get(f"{VM_URL}/api/v1/query", {"query": q})
    if not body:
        return 0.0
    try:
        results = json.loads(body).get("data", {}).get("result", [])
        return float(results[0]["value"][1]) if results else 0.0
    except Exception:
        return 0.0


def vl_count(q: str) -> int:
    """Count matching events in VictoriaLogs (NDJSON, one object per line)."""
    body = http_get(f"{VL_URL}/select/logsql/query", {"query": q, "limit": "10000"})
    if body is None:
        return -1
    return len([l for l in body.splitlines() if l.strip()])

# ── Convoy helpers ────────────────────────────────────────────────────────────

def convoy_landed() -> bool:
    rc, output = run_gt(["convoy", "list", "--all", "--json"])
    if rc != 0 or not output.strip():
        return False
    try:
        convoys = json.loads(output)
        if not isinstance(convoys, list):
            return False
        for c in convoys:
            title = (c.get("title", "") + c.get("name", "")).lower()
            status = c.get("status", "").lower()
            if ("crypto" in title or "tales" in title) and status in ("closed", "landed"):
                return True
    except Exception:
        pass
    return False

# ── Phase functions ───────────────────────────────────────────────────────────

def phase1_reset_otel() -> None:
    section("PHASE 1 — Reset OpenTelemetry")
    with Report(REPORTS_DIR / "01-otel-reset.md", "Phase 1 — Reset OpenTelemetry") as r:
        r.p("Stops the docker-compose stack and removes all named volumes "
            "so the next run starts with a completely clean telemetry slate.")

        r.h2("docker compose down")
        rc, out = run_compose(["down"])
        r.cmd("docker compose down", out)

        r.h2("Remove volumes")
        volumes = [
            f"{COMPOSE_PROJECT}_vm-data",
            f"{COMPOSE_PROJECT}_vl-data",
            f"{COMPOSE_PROJECT}_grafana-data",
        ]
        rc, out = run_cmd(["docker", "volume", "rm"] + volumes)
        r.cmd(f"docker volume rm {' '.join(volumes)}", out)

        rc, out = run_cmd(["docker", "volume", "ls", "--filter", f"name={COMPOSE_PROJECT}"])
        r.cmd(f"docker volume ls --filter name={COMPOSE_PROJECT}", out)


def phase2_reset_gastown() -> None:
    section("PHASE 2 — Reset Gastown")
    with Report(REPORTS_DIR / "02-gastown-reset.md", "Phase 2 — Reset Gastown") as r:
        r.p(
            "Stops the Mayor session so the next run starts clean.\n\n"
            f"Global town root: `{TOWN_DIR}`"
        )

        r.h2("Mayor status before reset")
        rc, out = run_gt(["mayor", "status"])
        r.code(out)

        r.h2("Stop Mayor")
        rc, out = run_gt(["mayor", "stop"])
        r.cmd("gt mayor stop", out)


def phase3_start_otel() -> tuple[subprocess.Popen, dict]:
    section("PHASE 3 — Start OTEL stack + gastown-trace")
    with Report(REPORTS_DIR / "03-otel-start.md", "Phase 3 — OTEL Stack + gastown-trace") as r:

        r.h2("docker compose up")
        rc, out = run_compose(["up", "-d"])
        r.cmd("docker compose up -d", out)
        if rc != 0:
            r.blockquote(f"⚠ docker compose up returned {rc}")

        vm_ok = wait_for_http(f"{VM_URL}/health", "VictoriaMetrics")
        vl_ok = wait_for_http(f"{VL_URL}/health", "VictoriaLogs")

        r.h2("gastown-trace")
        trace_log = (REPORTS_DIR / "gastown-trace.log").open("w")
        trace_proc = subprocess.Popen(
            [str(TRACE_BIN), "--logs", VL_URL, "--port", str(TRACE_PORT)],
            stdout=trace_log,
            stderr=subprocess.STDOUT,
        )
        time.sleep(2)
        alive = trace_proc.poll() is None
        r.p(f"PID {trace_proc.pid} → {TRACE_URL} — {'running' if alive else 'FAILED TO START'}")

        r.h2("OTEL Environment")
        r.code("\n".join(f"{k}={v}" for k, v in OTEL_VARS.items()))

        r.h2("Services Health")
        r.table(
            ["Service", "URL", "Status"],
            [
                ["VictoriaMetrics", f"{VM_URL}/health", "OK" if vm_ok else "UNREACHABLE"],
                ["VictoriaLogs",    f"{VL_URL}/health", "OK" if vl_ok else "UNREACHABLE"],
                ["gastown-trace",  TRACE_URL,          f"PID {trace_proc.pid}" if alive else "FAILED"],
                ["Grafana",        GRAFANA_URL,        "started (may take 10s)"],
            ],
        )

    return trace_proc, OTEL_VARS


def phase4_start_gastown() -> bool:
    section("PHASE 4 — Init Gastown + start Mayor")
    mayor_ready = False
    with Report(REPORTS_DIR / "04-gastown-start.md", "Phase 4 — Start Mayor") as r:
        r.p(f"Starting Mayor in global town: `{TOWN_DIR}`")

        r.h2("gt mayor start")
        rc, out = run_gt(["mayor", "start"])
        r.cmd("gt mayor start", out)

        r.h2("Waiting for Mayor")
        log("Polling gt mayor status…")
        for i in range(30):
            rc, out = run_gt(["mayor", "status"])
            if rc == 0 and any(w in out.lower() for w in ("running", "active")):
                mayor_ready = True
                log("Mayor is running")
                break
            time.sleep(2)

        r.code(out, "")
        r.status(mayor_ready, "Mayor running" if mayor_ready else "Mayor not ready after 60s")
        return mayor_ready


def phase5_launch_test() -> None:
    section("PHASE 5 — Inject PROMPT1.md → Mayor")
    prompt = PROMPT_FILE.read_text()

    with Report(REPORTS_DIR / "05-test-launch.md", "Phase 5 — Test Suite Launch") as r:
        r.h2("Prompt Content")
        r.write(prompt + "\n\n---\n\n")

        r.h2("Nudge delivery")
        rc, out = run_gt(["nudge", "mayor", prompt])
        r.cmd("gt nudge mayor <PROMPT1.md content>", out)
        r.status(rc == 0, "Nudge delivered" if rc == 0 else f"Nudge failed (rc={rc})")


def phase6_wait_convoy() -> tuple[bool, int]:
    section(f"PHASE 6 — Waiting for convoy (timeout: {CONVOY_TIMEOUT}s)")
    landed = False
    elapsed = 0

    with Report(REPORTS_DIR / "06-test-results.md", "Phase 6 — Test Results") as r:
        r.blockquote(
            f"Polling every {CONVOY_POLL}s, timeout {CONVOY_TIMEOUT}s"
        )
        r.h2("Poll Log")

        while elapsed < CONVOY_TIMEOUT:
            if convoy_landed():
                landed = True
                log("Convoy LANDED ✓")
                r.write(f"- `{datetime.now().strftime('%H:%M:%S')}` [{elapsed}s] — **LANDED** ✓\n")
                break
            log(f"[{elapsed}/{CONVOY_TIMEOUT}s] Convoy not yet landed…")
            r.write(f"- `{datetime.now().strftime('%H:%M:%S')}` [{elapsed}s] — open\n")
            time.sleep(CONVOY_POLL)
            elapsed += CONVOY_POLL

        r.h2("Convoy Status")
        rc, out = run_gt(["convoy", "list", "--all"])
        r.code(out)

        r.h2("Doctor")
        rc, out = run_gt(["doctor"])
        r.code(out)

        r.h2("Recent Agent Activity")
        rc, out = run_gt(["trail", "commits", "--limit", "20"])
        r.code(out)

        if landed:
            r.blockquote(f"Convoy **LANDED** ✓ after {elapsed}s")
        else:
            r.blockquote(f"⚠ Timeout after {elapsed}s — convoy still open")

    return landed, elapsed


def phase7_collect_otel() -> None:
    section("PHASE 7 — Collect OTEL metrics + logs")
    with Report(REPORTS_DIR / "07-otel-data.md", "Phase 7 — OTEL Data") as r:

        r.h2("Gastown Metrics (VictoriaMetrics)")
        metrics = {
            "bd calls by subcommand":     "sum by (subcommand)(gastown_bd_calls_total)",
            "polecat spawns":             "gastown_polecat_spawns_total",
            "session starts":             "gastown_session_starts_total",
            "session stops":              "gastown_session_stops_total",
            "nudges":                     "gastown_nudge_total",
            "work completed (gt done)":   "gastown_done_total",
            "convoy creates":             "gastown_convoy_creates_total",
            "slings dispatched":          "gastown_sling_dispatches_total",
        }
        lines = []
        for label, q in metrics.items():
            lines.append(f"{label}:\n{vm_query(q)}")
        r.code("\n\n".join(lines))

        r.h2("Token Usage")
        token_metrics = {
            "input tokens by model":   "sum by (model)(bd_ai_input_tokens_total)",
            "output tokens by model":  "sum by (model)(bd_ai_output_tokens_total)",
            "API latency P95 (ms)":    "histogram_quantile(0.95, bd_ai_request_duration_ms_bucket)",
        }
        lines = []
        for label, q in token_metrics.items():
            lines.append(f"{label}:\n{vm_query(q)}")
        r.code("\n\n".join(lines))

        r.h2("bd Storage")
        storage_metrics = {
            "storage operations by type":  "sum by (operation)(bd_storage_operations_total)",
            "storage errors":              "bd_storage_errors_total",
            "issues by status":            "bd_issue_count",
        }
        lines = []
        for label, q in storage_metrics.items():
            lines.append(f"{label}:\n{vm_query(q)}")
        r.code("\n\n".join(lines))

        r.h2("VictoriaLogs — Event Counts")
        vl_queries = {
            "All gastown events":    "service_name:gastown",
            "session.start":         'service_name:gastown AND "session.start"',
            "session.stop":          'service_name:gastown AND "session.stop"',
            "polecat.spawn":         'service_name:gastown AND "polecat.spawn"',
            "sling dispatches":      "service_name:gastown AND sling",
            "mail operations":       "service_name:gastown AND mail",
            "nudges":                "service_name:gastown AND nudge",
            "gt done events":        "service_name:gastown AND done",
            "errors":                "service_name:gastown AND level:error",
            "Claude Code events":    "service.name:claude-code",
            "Claude API requests":   '"claude_code.api_request"',
            "Claude tool calls":     '"claude_code.tool_result"',
        }
        rows = []
        for label, q in vl_queries.items():
            n = vl_count(q)
            rows.append([label, str(n) if n >= 0 else "?"])
        r.table(["Event type", "Count"], rows)

        r.h2("Explore Further")
        r.table(
            ["What", "URL"],
            [
                ["All gastown events",  f"{VL_URL}/select/vmui/#/?query=service_name%3Agastown"],
                ["Live-tail",           f"{VL_URL}/select/vmui/#/?query=service_name%3Agastown&view=liveTailing"],
                ["Errors",              f"{VL_URL}/select/vmui/#/?query=service_name%3Agastown%20AND%20level%3Aerror"],
                ["Claude Code",         f"{VL_URL}/select/vmui/#/?query=service.name%3Aclaude-code"],
                ["Metrics VMUI",        f"{VM_URL}/vmui/#/?query=gastown_bd_calls_total"],
                ["Grafana",             GRAFANA_URL],
                ["gastown-trace",       TRACE_URL],
            ],
        )


def phase8_recommendations(
    landed: bool,
    elapsed: int,
    test_start: float,
    trace_pid: int,
) -> None:
    section("PHASE 8 — Recommendations")

    errors         = vl_count("service_name:gastown AND level:error")
    session_starts = vm_scalar("sum(gastown_session_starts_total)")
    polecat_spawns = vm_scalar("sum(gastown_polecat_spawns_total)")
    input_tokens   = vm_scalar("sum(bd_ai_input_tokens_total)")
    output_tokens  = vm_scalar("sum(bd_ai_output_tokens_total)")
    total_elapsed  = int(time.time() - test_start)

    with Report(REPORTS_DIR / "08-recommendations.md", "Phase 8 — Recommendations") as r:

        r.h2("Run Summary")
        r.table(
            ["Metric", "Value"],
            [
                ["Convoy landed",             "Yes ✓" if landed else f"No (timeout at {elapsed}s)"],
                ["Total test duration",        f"{total_elapsed}s"],
                ["Claude sessions started",    str(int(session_starts))],
                ["Polecats spawned",           str(int(polecat_spawns))],
                ["Input tokens",              f"{int(input_tokens):,}"],
                ["Output tokens",             f"{int(output_tokens):,}"],
                ["Errors in logs",             str(errors) if errors >= 0 else "?"],
            ],
        )

        r.h2("Recommendations")
        n = 1

        # ── Convoy status ──
        if not landed:
            r.h3(f"{n}. Convoy did not land — investigate agent states")
            n += 1
            r.p(f'The convoy "The Crypto Tales" did not reach LANDED within {CONVOY_TIMEOUT}s.')
            r.code(
                "\n".join([
                    f"cd {TOWN_DIR}",
                    "gt convoy list --all --tree   # full convoy state",
                    "gt agents                      # list running sessions",
                    "gt ready                       # work stuck as pending?",
                    "gt doctor                      # health check",
                ]),
                "bash",
            )

        # ── Errors ──
        if errors > 0:
            r.h3(f"{n}. {errors} error(s) detected in logs")
            n += 1
            r.p("Investigate in VictoriaLogs:")
            r.code('service_name:gastown AND level:error', "logsql")
            r.p(f"→ [{VL_URL}/select/vmui/…]"
                f"({VL_URL}/select/vmui/#/?query=service_name%3Agastown%20AND%20level%3Aerror)")

        # ── Polecat count ──
        spawns = int(polecat_spawns)
        if spawns == 0:
            r.h3(f"{n}. No polecats were spawned")
            n += 1
            r.p(
                "PROMPT1.md requires 3 polecats (alice, bob, eve). None were spawned.\n\n"
                "Possible causes: Mayor did not receive the mail, Mayor session crashed, "
                "or rig initialization failed.\n\n"
                "Attach to the Mayor: `gt mayor attach`"
            )
        elif spawns != 3:
            r.h3(f"{n}. Unexpected polecat count: {spawns} (expected 3)")
            n += 1
            if spawns < 3:
                r.p(f"Only {spawns}/3 agents started. Check `gt ready` for unassigned issues.")
            else:
                r.p(f"{spawns} polecats spawned — Mayor may have created retries or parallel tracks. "
                    "Check `gt trail` and `gt convoy list --tree`.")

        # ── Token usage ──
        if input_tokens > 100_000:
            r.h3(f"{n}. High input token usage ({int(input_tokens):,} tokens)")
            n += 1
            r.p(
                "Consider:\n\n"
                "- Run `gt compact` between test runs to clean expired wisps\n"
                "- Review `gt prime` formula length — shorten boilerplate in agent context\n"
                "- Check `gt costs` for per-session breakdown"
            )

        # ── Python crypto chain ──
        r.h3(f"{n}. Verify Python crypto deliverables")
        n += 1
        r.p("Once polecats are done, run the end-to-end OpenSSL chain:")
        r.code(
            "\n".join([
                f"cd {TOWN_DIR}",
                "gt rig list                          # find alice/bob/eve repos",
                "# then from a shared working directory:",
                "python alice.py && python bob.py && python eve.py",
            ]),
            "bash",
        )
        r.p(
            "Expected:\n\n"
            '- `bob.py` decrypts and prints: **"Meet me at the old cipher tree at midnight."**\n'
            "- `eve.py` raises a decryption exception — confirming RSA-OAEP is unbreakable without "
            "the private key."
        )

        # ── Claude Code OTEL coverage ──
        r.h3(f"{n}. Check Claude Code OTLP coverage per agent")
        n += 1
        r.p("Each polecat session should emit telemetry tagged with `gt.role` and `gt.rig`:")
        r.code("service.name:claude-code AND gt.role:*", "logsql")
        r.p(
            "If a session is missing, it did not inherit `CLAUDE_CODE_ENABLE_TELEMETRY=1`.\n"
            "Ensure `GT_OTEL_METRICS_URL` was exported **before** `gt mayor start`."
        )

        # ── gastown-trace ──
        r.h3(f"{n}. Explore traces in gastown-trace")
        n += 1
        r.p(
            f"gastown-trace is running at **{TRACE_URL}** (PID {trace_pid}).\n\n"
            "Key views:\n\n"
            "- Session transcripts for alice, bob, and eve\n"
            "- Bead lifecycle: issue open → in_progress → done\n"
            "- Delegation chain: Mayor → polecats\n"
            "- Cost breakdown per session\n"
            "- Waterfall view of parallel work"
        )

        # ── Grafana ──
        r.h3(f"{n}. Review Grafana dashboards")
        n += 1
        r.p(f"Open [Grafana]({GRAFANA_URL}) (admin/admin) for pre-built dashboards.")
        r.code(
            "\n".join([
                "# bd calls per second",
                "rate(gastown_bd_calls_total[5m])",
                "",
                "# Polecat spawn rate",
                "increase(gastown_polecat_spawns_total[1h])",
                "",
                "# Token cost by model",
                "sum by (model)(bd_ai_input_tokens_total + bd_ai_output_tokens_total)",
            ]),
            "promql",
        )

        r.write(f"\n---\n\n*Generated by `run_full.py` — {ts()}*\n")

# ── Main ──────────────────────────────────────────────────────────────────────

def preflight() -> None:
    errors = []
    for cmd in ("docker", "git", "gt"):
        if not shutil.which(cmd):
            errors.append(f"Command not found: {cmd}")
    if not PROMPT_FILE.exists():
        errors.append(f"Prompt file not found: {PROMPT_FILE}")
    if not TRACE_BIN.exists():
        errors.append(f"gastown-trace binary not found: {TRACE_BIN}")
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


def write_readme(trace_pid: int) -> None:
    with Report(REPORTS_DIR / "README.md", f"Gastown Test Run — {TIMESTAMP}") as r:
        r.h2("Overview")
        r.p("Full test cycle: OTEL reset → Gastown reset → stack start → test suite → recommendations.")
        r.h2("Reports")
        r.table(
            ["#", "File", "Phase"],
            [
                ["1", "[01-otel-reset.md](01-otel-reset.md)",       "Reset OpenTelemetry data"],
                ["2", "[02-gastown-reset.md](02-gastown-reset.md)", "Reset Gastown instance"],
                ["3", "[03-otel-start.md](03-otel-start.md)",       "Start OTEL stack + gastown-trace"],
                ["4", "[04-gastown-start.md](04-gastown-start.md)", "Init Gastown workspace + Mayor"],
                ["5", "[05-test-launch.md](05-test-launch.md)",     "Launch test suite (PROMPT1.md → Mayor)"],
                ["6", "[06-test-results.md](06-test-results.md)",   "Test results (convoy landing)"],
                ["7", "[07-otel-data.md](07-otel-data.md)",         "OTEL metrics + logs collected"],
                ["8", "[08-recommendations.md](08-recommendations.md)", "Recommendations"],
            ],
        )
        r.h2("Quick Links")
        r.table(
            ["Service", "URL"],
            [
                ["gastown-trace",       TRACE_URL],
                ["Grafana",             f"{GRAFANA_URL} (admin/admin)"],
                ["VictoriaMetrics VMUI", f"{VM_URL}/vmui/"],
                ["VictoriaLogs live-tail", f"{VL_URL}/select/vmui/#/?query=service_name%3Agastown&view=liveTailing"],
            ],
        )
        r.write(f"\ngatown-trace PID: {trace_pid}\n")


def main() -> None:
    global _log_file

    preflight()

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    _log_file = REPORTS_DIR / "run.log"
    (SCRIPT_DIR / "reports" / "latest").unlink(missing_ok=True)
    (SCRIPT_DIR / "reports" / "latest").symlink_to(REPORTS_DIR)

    log(f"Reports: {REPORTS_DIR}")
    log(f"Symlink: {SCRIPT_DIR / 'reports' / 'latest'}")

    trace_proc = None

    def _cleanup(sig=None, frame=None):
        # gastown-trace is intentionally left running as a daemon
        print(f"\ngatown-trace (PID {trace_proc.pid if trace_proc else '?'}) left running.",
              flush=True)

    signal.signal(signal.SIGINT, _cleanup)
    signal.signal(signal.SIGTERM, _cleanup)

    # ── Phases ──
    phase1_reset_otel()
    phase2_reset_gastown()

    trace_proc, _ = phase3_start_otel()
    write_readme(trace_proc.pid)

    mayor_ready = phase4_start_gastown()
    if not mayor_ready:
        log("WARNING: Mayor not confirmed running — continuing anyway")

    test_start = time.time()
    phase5_launch_test()

    landed, elapsed = phase6_wait_convoy()
    phase7_collect_otel()
    phase8_recommendations(landed, elapsed, test_start, trace_proc.pid)

    # ── Summary ──
    section("DONE")
    print(f"Reports: {REPORTS_DIR}/")
    print(f"Symlink: {SCRIPT_DIR / 'reports' / 'latest'}")
    print()
    for i in range(1, 9):
        labels = {
            1: "01-otel-reset.md         — OTEL reset",
            2: "02-gastown-reset.md      — Gastown instance reset",
            3: "03-otel-start.md         — OTEL stack + gastown-trace",
            4: "04-gastown-start.md      — Gastown init + Mayor",
            5: "05-test-launch.md        — Test suite launch",
            6: "06-test-results.md       — Convoy results + doctor",
            7: "07-otel-data.md          — Metrics + log counts",
            8: "08-recommendations.md    — Recommendations",
        }
        print(f"  {labels[i]}")
    print()
    print(f"gastown-trace: {TRACE_URL}  (PID {trace_proc.pid} — still running)")
    print(f"Grafana:       {GRAFANA_URL}")
    print()


if __name__ == "__main__":
    main()
