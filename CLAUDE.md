# Gastown Tests — Context

## Source Locations

| Project | Path |
|---------|------|
| **Gastown** (CLI `gt`, agents, core) | `~/dev/third-party/gastown` |
| **Gastown OTEL** (observability infrastructure) | `$GASTOWN_OTEL_DIR` (default: `~/dev/third-party/gastown-otel`) |
| **gastown-trace** (OpenTelemetry visualization back/front) | `$GASTOWN_OTEL_DIR/gastown-trace` |

### Content of gastown-otel

- `docker-compose.yml` — VictoriaMetrics + VictoriaLogs + Grafana stack
- `gastown-trace/` — back/front application for visualizing Gastown OpenTelemetry traces
- `grafana/provisioning/` — pre-configured Grafana datasources and dashboards

### Exposed Ports (localhost only)

| Service | Port |
|---------|------|
| VictoriaMetrics | 8428 |
| VictoriaLogs | 9428 |
| Grafana | 9429 |

---

## OpenTelemetry Commands

> **Note:** Replace `$GASTOWN_OTEL_DIR` with your path if not set. Default: `~/dev/third-party/gastown-otel`

### Start the stack

```bash
docker compose -f ${GASTOWN_OTEL_DIR:-~/dev/third-party/gastown-otel}/docker-compose.yml up -d
```

### Stop the stack

```bash
docker compose -f ${GASTOWN_OTEL_DIR:-~/dev/third-party/gastown-otel}/docker-compose.yml down
```

### Complete OpenTelemetry data reset (⚠ erases all metrics/logs/traces)

```bash
docker compose -f ${GASTOWN_OTEL_DIR:-~/dev/third-party/gastown-otel}/docker-compose.yml down && \
docker volume rm gastown-otel_vm-data gastown-otel_vl-data gastown-otel_grafana-data 2>/dev/null || true && \
docker compose -f ${GASTOWN_OTEL_DIR:-~/dev/third-party/gastown-otel}/docker-compose.yml up -d
```

### View stack logs

```bash
docker compose -f ${GASTOWN_OTEL_DIR:-~/dev/third-party/gastown-otel}/docker-compose.yml logs -f
```

---

## Scripts

### `run-full.sh` — full cycle (recommended)

Runs all phases in a single launch and writes each step to `reports/TIMESTAMP/*.md`:

| Phase | Generated file | Description |
|-------|---------------|-------------|
| 1 | `01-otel-reset.md` | OTEL reset (docker volumes) |
| 2 | `02-gastown-reset.md` | Gastown instance reset |
| 3 | `03-otel-start.md` | OTEL stack + gastown-trace startup |
| 4 | `04-gastown-start.md` | Workspace init + Mayor |
| 5 | `05-test-launch.md` | PROMPT1.md injection to Mayor |
| 6 | `06-test-results.md` | Convoy + doctor + trail wait |
| 7 | `07-otel-data.md` | Metrics + VictoriaLogs counts |
| 8 | `08-recommendations.md` | Recommendations |

```bash
./run-full.sh
# Reports are in reports/latest/
# gastown-trace stays active until Ctrl-C
```

Default timeout: 1h. Configurable:

```bash
CONVOY_TIMEOUT=7200 ./run-full.sh   # 2h
```

### `run-test.sh` — injection only (minimal)

Creates (or reuses) the `gt-test-instance/` folder in this project, initializes Gastown,
starts the Mayor and injects `PROMPT1.md` — without reset or OTEL.

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTANCE_DIR="$SCRIPT_DIR/gt-test-instance"
PROMPT_FILE="$SCRIPT_DIR/PROMPT1.md"

if [[ ! -f "$PROMPT_FILE" ]]; then
  echo "ERROR: $PROMPT_FILE not found" >&2
  exit 1
fi

# 1. Prepare instance directory
mkdir -p "$INSTANCE_DIR"
cd "$INSTANCE_DIR"

if [[ ! -d ".git" ]]; then
  git init
  git commit --allow-empty -m "init: gastown test instance"
fi

# 2. Initialize Gastown structure (idempotent with --force)
gt init --force

# 3. Start Mayor (no-op if already running)
gt mayor start || true

# 4. Wait for Mayor session to be ready
echo "Waiting for Mayor..."
for i in $(seq 1 30); do
  if gt mayor status 2>/dev/null | grep -q "running\|active"; then
    break
  fi
  sleep 2
done

# 5. Inject PROMPT1.md to Mayor
PROMPT_CONTENT="$(cat "$PROMPT_FILE")"
gt mail send mayor/ \
  --subject "Test scenario: PROMPT1" \
  --message "$PROMPT_CONTENT" \
  --type task \
  --priority 1

echo "PROMPT1.md sent to Mayor in $INSTANCE_DIR"
```

Save this script as `run-test.sh` at the root of this project, then:

```bash
chmod +x run-test.sh
./run-test.sh
```
