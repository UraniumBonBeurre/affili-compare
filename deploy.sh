#!/bin/sh
# deploy.sh — Déploiement Vercel + gestion des versions
#
# Usage :
#   ./deploy.sh              → déploie en production
#   ./deploy.sh list         → liste les 10 dernières versions
#   ./deploy.sh rollback     → rollback interactif vers une version précédente

CMD=${1:-deploy}

case "$CMD" in

  deploy)
    echo "→ Déploiement en production…"
    vercel --prod
    ;;

  list|ls)
    echo "→ 10 dernières versions :"
    vercel ls --prod 2>/dev/null | head -12
    ;;

  rollback)
    echo "→ Versions disponibles :"
    vercel ls --prod 2>/dev/null | head -12
    echo ""
    printf "URL ou ID de la version cible (vide = dernière) : "
    read -r target
    if [ -z "$target" ]; then
      vercel rollback
    else
      vercel rollback "$target"
    fi
    ;;

  *)
    echo "Usage : ./deploy.sh [deploy|list|rollback]"
    exit 1
    ;;

esac
