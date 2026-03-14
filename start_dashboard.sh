#!/usr/bin/env bash
# start_dashboard.sh — Lance le serveur Next.js et ouvre le dashboard taxonomie
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PORT="${PORT:-3000}"
URL="http://localhost:${PORT}/admin/taxonomy"

echo "▶  Démarrage du serveur Next.js (port $PORT)…"
echo "   Dashboard : $URL"
echo "   Arrêt     : Ctrl+C"
echo ""

# Ouvre le navigateur dès que le serveur répond
(
  for i in $(seq 1 30); do
    sleep 1
    if curl -s -o /dev/null -w "%{http_code}" "http://localhost:${PORT}" 2>/dev/null | grep -q "^[23]"; then
      if command -v open &>/dev/null; then
        open "$URL"
      elif command -v xdg-open &>/dev/null; then
        xdg-open "$URL"
      fi
      break
    fi
  done
) &

npx next dev --port "$PORT"
