# Gastown Tests — Context

## Source Locations

| Projet | Chemin |
|--------|--------|
| **Gastown** (CLI `gt`, agents, core) | `/Users/pa/dev/third-party/gastown` |
| **Gastown OTEL** (infra d'observabilité) | `/Users/pa/dev/third-party/gastown-otel` |
| **gastown-trace** (back/front visualisation OpenTelemetry) | `/Users/pa/dev/third-party/gastown-otel/gastown-trace` |

### Contenu de gastown-otel

- `docker-compose.yml` — stack VictoriaMetrics + VictoriaLogs + Grafana
- `gastown-trace/` — application back/front de visualisation des traces OpenTelemetry de gastown
- `grafana/provisioning/` — datasources et dashboards Grafana pré-configurés

### Ports exposés (localhost uniquement)

| Service | Port |
|---------|------|
| VictoriaMetrics | 8428 |
| VictoriaLogs | 9428 |
| Grafana | 9429 |

---

## Commandes OpenTelemetry

### Démarrer la stack
```bash
docker compose -f /Users/pa/dev/third-party/gastown-otel/docker-compose.yml up -d
```

### Arrêter la stack
```bash
docker compose -f /Users/pa/dev/third-party/gastown-otel/docker-compose.yml down
```

### Reset complet des données OpenTelemetry (⚠ efface toutes les métriques/logs/traces)
```bash
docker compose -f /Users/pa/dev/third-party/gastown-otel/docker-compose.yml down && \
docker volume rm gastown-otel_vm-data gastown-otel_vl-data gastown-otel_grafana-data 2>/dev/null || true && \
docker compose -f /Users/pa/dev/third-party/gastown-otel/docker-compose.yml up -d
```

### Voir les logs de la stack
```bash
docker compose -f /Users/pa/dev/third-party/gastown-otel/docker-compose.yml logs -f
```

---

## Scripts

### `run-full.sh` — cycle complet (recommandé)

Enchaîne toutes les phases en un seul lancement et écrit chaque étape dans `reports/TIMESTAMP/*.md` :

| Phase | Fichier généré | Description |
|-------|---------------|-------------|
| 1 | `01-otel-reset.md` | Reset OTEL (docker volumes) |
| 2 | `02-gastown-reset.md` | Reset instance Gastown |
| 3 | `03-otel-start.md` | Démarrage stack OTEL + gastown-trace |
| 4 | `04-gastown-start.md` | Init workspace + Mayor |
| 5 | `05-test-launch.md` | Injection PROMPT1.md au Mayor |
| 6 | `06-test-results.md` | Attente convoy + doctor + trail |
| 7 | `07-otel-data.md` | Métriques + counts VictoriaLogs |
| 8 | `08-recommendations.md` | Recommandations |

```bash
./run-full.sh
# Les rapports sont dans reports/latest/
# gastown-trace reste actif jusqu'au Ctrl-C
```

Timeout par défaut : 1h. Configurable :
```bash
CONVOY_TIMEOUT=7200 ./run-full.sh   # 2h
```

### `run-test.sh` — injection seule (minimal)

Crée (ou réutilise) le dossier `gt-test-instance/` dans ce projet, initialise Gastown,
démarre le Mayor et injecte `PROMPT1.md` — sans reset ni OTEL.

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTANCE_DIR="$SCRIPT_DIR/gt-test-instance"
PROMPT_FILE="$SCRIPT_DIR/PROMPT1.md"

if [[ ! -f "$PROMPT_FILE" ]]; then
  echo "ERREUR : $PROMPT_FILE introuvable" >&2
  exit 1
fi

# 1. Préparer le répertoire de l'instance
mkdir -p "$INSTANCE_DIR"
cd "$INSTANCE_DIR"

if [[ ! -d ".git" ]]; then
  git init
  git commit --allow-empty -m "init: gastown test instance"
fi

# 2. Initialiser la structure Gastown (idempotent avec --force)
gt init --force

# 3. Démarrer le Mayor (no-op s'il tourne déjà)
gt mayor start || true

# 4. Attendre que la session Mayor soit prête
echo "Attente du Mayor..."
for i in $(seq 1 30); do
  if gt mayor status 2>/dev/null | grep -q "running\|active"; then
    break
  fi
  sleep 2
done

# 5. Injecter PROMPT1.md au Mayor
PROMPT_CONTENT="$(cat "$PROMPT_FILE")"
gt mail send mayor/ \
  --subject "Test scenario: PROMPT1" \
  --message "$PROMPT_CONTENT" \
  --type task \
  --priority 1

echo "PROMPT1.md envoyé au Mayor dans $INSTANCE_DIR"
```

Sauvegarder ce script sous `run-test.sh` à la racine de ce projet, puis :

```bash
chmod +x run-test.sh
./run-test.sh
```
