#!/bin/sh
# Lance le serveur Next.js sur le premier port libre dès 3000

PORT=3000
while lsof -i TCP:"$PORT" -sTCP:LISTEN -t >/dev/null 2>&1; do
  PORT=$((PORT + 1))
done

echo "→ http://localhost:$PORT"
npm run dev -- --port "$PORT"
