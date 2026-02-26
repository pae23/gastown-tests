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
