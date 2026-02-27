# gastown-tests

Test harness for [Gastown](https://github.com/steveyegge/gastown) multi-agent scenarios with full
OpenTelemetry observability (VictoriaMetrics + VictoriaLogs + Grafana + gastown-trace).

---

## What's in this repo

| File | Purpose |
|------|---------|
| `run_full.py` | Full test cycle — OTEL reset, Mayor start, test inject, convoy poll, reports |
| `PROMPT1.md` | Test scenario: "The Crypto Tales" (alice / bob / eve + Python OpenSSL) |
| `CLAUDE.md` | Source paths and reference commands for Claude Code agents |

---

## Prerequisites

### Required repos (sibling directories expected at these paths)

| Repo | Path | Role |
|------|------|------|
| [gastown](https://github.com/steveyegge/gastown) | `~/dev/third-party/gastown` | `gt` CLI binary |
| [gastown-otel](https://github.com/steveyegge/gastown-otel) | `~/dev/third-party/gastown-otel` | docker-compose stack + gastown-trace |

> **Note:** `run_full.py` uses the `GASTOWN_OTEL_DIR` environment variable.
> Set it if your layout differs from `~/dev/third-party/gastown-otel`:
> ```bash
> export GASTOWN_OTEL_DIR=/path/to/your/gastown-otel
> python3 run_full.py
> ```

### Required tools

```
gt       — Gastown CLI (must be in PATH)
bd       — Beads issue tracker (must be in PATH)
docker   — Docker with Compose v2
python3  — Python 3.10+
gh       — GitHub CLI (only for this repo management)
```

### ⚠️ docker-compose.yml image fix (gastown-otel)

The upstream `gastown-otel/docker-compose.yml` may reference image tags that no longer exist on
Docker Hub. The following tags are known to work with locally cached images:

```yaml
# gastown-otel/docker-compose.yml — verified working tags
victoriametrics/victoria-metrics:v1.136.0   # was: v1.122.1
victoriametrics/victoria-logs:v1.45.0       # was: v1.45.0-victorialogs (does not exist)
grafana/grafana:12.3.3                       # was: 12.4.0
```

Apply the fix before first run (replace `GASTOWN_OTEL_DIR` with your path if different):

```bash
sed -i '' \
  's|victoria-metrics:v1.122.1|victoria-metrics:v1.136.0|' \
  's|victoria-logs:v1.45.0-victorialogs|victoria-logs:v1.45.0|' \
  's|grafana:12.4.0|grafana:12.3.3|' \
  ${GASTOWN_OTEL_DIR:-~/dev/third-party/gastown-otel}/docker-compose.yml
```

### gastown-trace binary

`gastown-trace` must be compiled before first run:

```bash
cd ${GASTOWN_OTEL_DIR:-~/dev/third-party/gastown-otel}/gastown-trace
go build -o gastown-trace .
```

---

## Architecture notes

```
~/gt/                    ← global Gastown town root (always used by gt commands)
├── mayor/               ← Mayor agent workspace
├── alice/               ← rig created by Mayor for alice polecat
├── bob/                 ← rig created by Mayor for bob polecat
├── eve/                 ← rig created by Mayor for eve polecat
└── .beads/              ← beads issue store (requires dolt server)
```

**Key insight discovered during testing:** `gt mayor start` always operates in the global town
(`~/gt/`). Creating a subdirectory and running `gt init` there initialises a *rig* (a git repo for
agents to work on), not an isolated town. All `gt` commands in `run_full.py` therefore run from
`TOWN_DIR = ~/gt/`.

---

## Usage

```bash
# Default (1h convoy timeout)
python3 run_full.py

# Custom timeout
CONVOY_TIMEOUT=1800 python3 run_full.py
```

Reports are written to `reports/TIMESTAMP/` and symlinked to `reports/latest/`.

---

## What run_full.py does

| Phase | Output file | Description |
|-------|-------------|-------------|
| 1 | `01-otel-reset.md` | `docker compose down` + remove volumes (clean slate) |
| 2 | `02-gastown-reset.md` | `gt mayor stop` |
| 3 | `03-otel-start.md` | `docker compose up -d`, wait for health, start gastown-trace |
| 4 | `04-gastown-start.md` | `gt mayor start`, poll until running |
| 5 | `05-test-launch.md` | `gt nudge mayor <PROMPT1.md>` |
| 6 | `06-test-results.md` | Poll `gt convoy list` every 30s until LANDED or timeout |
| 7 | `07-otel-data.md` | Query VictoriaMetrics (PromQL) + VictoriaLogs (LogsQL) |
| 8 | `08-recommendations.md` | Conditional recommendations from collected data |

### Observability stack

| Service | URL | Credentials |
|---------|-----|-------------|
| gastown-trace | http://localhost:7428 | — |
| Grafana | http://localhost:9429 | admin / admin |
| VictoriaMetrics VMUI | http://localhost:8428/vmui/ | — |
| VictoriaLogs | http://localhost:9428/select/vmui/ | — |

gastown-trace stays running as a daemon after `run_full.py` exits.
Stop it with `pkill gastown-trace`.

---

## Test scenario — PROMPT1.md

**"The Crypto Tales"** — three agents implement the Alice-and-Bob cryptography story from
[Wikipedia](https://en.wikipedia.org/wiki/Alice_and_Bob), each producing:

- `chapter.md` — narrative from their character's perspective
- a Python script using `cryptography` (pyca/cryptography, OpenSSL bindings)

| Agent | Script | Role |
|-------|--------|------|
| alice | `alice.py` | Generate RSA keypair, encrypt+sign message with Bob's pubkey |
| bob | `bob.py` | Decrypt+verify, print plaintext, encrypt reply |
| eve | `eve.py` | Intercept traffic, attempt decryption (must fail), document |

End-to-end verification:

```bash
python alice.py && python bob.py && python eve.py
# bob.py must print: "Meet me at the old cipher tree at midnight."
# eve.py must raise a decryption exception
```

---

## First run findings (2026-02-26)

### What worked
- Phases 1–5 completed in ~12 seconds
- Mayor session spawned and received the scenario prompt via `gt nudge`
- Mayor created alice/bob repos and began orchestrating polecats
- **7 092 Claude Code events** recorded in VictoriaLogs (3 383 API requests, 1 813 tool calls)
  — agents were actively working for the full hour

### Bugs found and fixed

| Bug | Symptom | Fix applied |
|-----|---------|-------------|
| `victoria-logs:v1.45.0-victorialogs` doesn't exist | `docker compose up` fails, stack never starts | Updated tags in docker-compose.yml |
| `gt mail send mayor/` requires `.beads/` | Mail delivery error, prompt never reached Mayor | Switched to `gt nudge mayor` (direct tmux delivery) |
| `gt init` doesn't create `.beads/` | Attempted to use `gt-test-instance/` as isolated town | Architecture fix: use global `~/gt/` town |
| Convoy poller ran in wrong directory | Convoy never detected as landed | Fixed `run_gt` to use `TOWN_DIR = ~/gt/` |
| `gastown_*` OTEL metrics empty | Mayor started before OTEL env vars were set | Ensure OTEL phase completes before Mayor start |

### Known remaining issue

`gastown_*` metrics (polecat spawns, slings, convoy creates) show no data because
`GT_OTEL_METRICS_URL` was not inherited by the Mayor session from the previous run.
The fixed `run_full.py` exports OTEL vars before starting the Mayor, so the next run
should capture full gastown telemetry.

---

## OTEL queries reference

### VictoriaMetrics (PromQL)

```promql
# bd call rate
rate(gastown_bd_calls_total[5m])

# Polecat spawn count
gastown_polecat_spawns_total

# Token usage by model
sum by (model)(bd_ai_input_tokens_total)
sum by (model)(bd_ai_output_tokens_total)

# API latency P95
histogram_quantile(0.95, bd_ai_request_duration_ms_bucket)
```

### VictoriaLogs (LogsQL)

```logsql
# All gastown events
service_name:gastown

# Polecat spawns only
service_name:gastown AND "polecat.spawn"

# Errors
service_name:gastown AND level:error

# Claude Code per agent
service.name:claude-code AND gt.role:*

# Claude API requests
"claude_code.api_request"
```
