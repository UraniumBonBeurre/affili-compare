#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# toggle_production_mode.sh — Active ou désactive la production automatique
#
# Usage :
#   ./toggle_production_mode.sh off
#       → retire les champs schedule des deux workflows, production_workflow=False
#
#   ./toggle_production_mode.sh on [--per_day N] [--top_nb K] [--variantes_nb X]
#       → ajoute N entrées cron réparties sur la journée, production_workflow=True,
#         met à jour nb_products_per_article et nb_pins_per_article dans settings.py
#
# Options (mode "on") :
#   --per_day      N  Nombre d'articles par jour   (défaut: 1)
#   --top_nb       K  Produits par article          (défaut: 5)
#   --variantes_nb X  Variantes de pins par article (défaut: 2)
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CREATE_YAML="$SCRIPT_DIR/.github/workflows/create_and_post_top_products.yaml"
UPDATE_YAML="$SCRIPT_DIR/.github/workflows/update_products_database.yaml"
SETTINGS_PY="$SCRIPT_DIR/settings.py"

MODE="${1:-}"
if [[ "$MODE" != "on" && "$MODE" != "off" ]]; then
  echo "Usage: $0 on [--per_day N] [--top_nb K] [--variantes_nb X]"
  echo "       $0 off"
  exit 1
fi
shift

# ── Parse optional arguments ───────────────────────────────────────────────
PER_DAY=1
TOP_NB=5
VARIANTES_NB=2

while [[ $# -gt 0 ]]; do
  case "$1" in
    --per_day)      PER_DAY="$2";      shift 2 ;;
    --top_nb)       TOP_NB="$2";       shift 2 ;;
    --variantes_nb) VARIANTES_NB="$2"; shift 2 ;;
    *) echo "❌  Argument inconnu: $1"; exit 1 ;;
  esac
done

echo "══════════════════════════════════════════════════"
echo "  🔀  toggle_production_mode  →  MODE = $MODE"
[[ "$MODE" == "on" ]] && echo "      per_day=$PER_DAY  top_nb=$TOP_NB  variantes_nb=$VARIANTES_NB"
echo "══════════════════════════════════════════════════"

# ── Python helper ──────────────────────────────────────────────────────────
python3 - "$MODE" "$PER_DAY" "$TOP_NB" "$VARIANTES_NB" \
          "$CREATE_YAML" "$UPDATE_YAML" "$SETTINGS_PY" << 'PYEOF'
import sys, re

mode          = sys.argv[1]
per_day       = int(sys.argv[2])
top_nb        = int(sys.argv[3])
variantes_nb  = int(sys.argv[4])
create_yaml      = sys.argv[5]
update_yaml_path = sys.argv[6]
settings_py      = sys.argv[7]

# ── 1. Cron schedule computation ──────────────────────────────────────────
def compute_crons(n):
    """n cron expressions evenly spread across the day (starting ~ 07h UTC)."""
    if n <= 0:
        return []
    if n == 1:
        return ["0 8 * * *"]
    interval = 24 // n
    start    = 7
    return [f"0 {(start + i * interval) % 24} * * *" for i in range(n)]

# ── 2. YAML manipulation helpers ──────────────────────────────────────────
def remove_schedule_block(text):
    """Remove the schedule: block from the YAML on: section."""
    return re.sub(r'  schedule:\n(?:    - cron: "[^"]*"\n)+', '', text)

def add_schedule_block(text, crons):
    """Insert schedule block just before  workflow_dispatch: in on: section."""
    lines = "  schedule:\n" + "".join(f'    - cron: "{c}"\n' for c in crons)
    return text.replace("  workflow_dispatch:\n", lines + "  workflow_dispatch:\n", 1)

def update_yaml(path, crons):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    text = remove_schedule_block(text)
    if crons:
        text = add_schedule_block(text, crons)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    status = f"schedule: {crons}" if crons else "no schedule"
    print(f"  ✅  {path.split('/')[-1]}  →  {status}")

# ── 3. settings.py manipulation ───────────────────────────────────────────
def update_settings(path, mode, top_nb, variantes_nb):
    with open(path, encoding="utf-8") as f:
        text = f.read()

    prod = "True" if mode == "on" else "False"
    text = re.sub(
        r'(production_workflow:\s*bool\s*=\s*)\w+',
        rf'\g<1>{prod}', text)
    text = re.sub(
        r'(nb_products_per_article:\s*int\s*=\s*)\d+',
        rf'\g<1>{top_nb}', text)
    text = re.sub(
        r'(nb_pins_per_article:\s*int\s*=\s*)\d+',
        rf'\g<1>{variantes_nb}', text)

    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"  ✅  settings.py  →  production_workflow={prod}, "
          f"nb_products={top_nb}, nb_pins={variantes_nb}")

# ── Run ────────────────────────────────────────────────────────────────────
if mode == "on":
    crons_create = compute_crons(per_day)
    crons_update = ["0 2 * * *"]       # DB update toujours à 02h UTC
else:
    crons_create = []
    crons_update = []

update_yaml(create_yaml,  crons_create)
update_yaml(update_yaml_path, crons_update)
update_settings(settings_py, mode, top_nb, variantes_nb)
PYEOF

# ── Git commit + push ──────────────────────────────────────────────────────
echo ""
echo "  📦  Commit + push…"
cd "$SCRIPT_DIR"
git add \
  .github/workflows/create_and_post_top_products.yaml \
  .github/workflows/update_products_database.yaml \
  settings.py

COMMIT_MSG="chore: production mode $MODE"
[[ "$MODE" == "on" ]] && COMMIT_MSG="chore: production mode ON (per_day=$PER_DAY, top_nb=$TOP_NB, variantes=$VARIANTES_NB)"

git diff --cached --quiet && echo "  ⚠️  Aucun changement à pousser." || {
  git commit -m "$COMMIT_MSG"
  git push origin "$(git branch --show-current)"
  echo "  ✅  Poussé sur $(git branch --show-current)"
}

echo ""
echo "  🎉  Mode $MODE activé."
