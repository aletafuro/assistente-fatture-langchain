#!/usr/bin/env bash
# Installa sul server una versione del bot presa da GitLab, SOLO se i test passano.
#   uso:   sudo /opt/bot-fatture/codice/server/aggiorna.sh v3.2
#   senza versione: mostra la versione installata e quelle disponibili.
# Se i test falliscono il bot in funzione non viene toccato. Per tornare indietro: stesso comando con la versione di prima.
set -euo pipefail
cd /opt/bot-fatture/codice

git fetch --tags --quiet
if [ $# -eq 0 ]; then
    echo "Versione installata: $(git describe --tags --always)"
    echo "Versioni disponibili:"; git tag --sort=-creatordate | head -10
    exit 0
fi

VERSIONE="$1"
git checkout --quiet "$VERSIONE"
echo "== Test della versione $VERSIONE dentro il container =="
docker build --target test -t bot-fatture-test . || {
    echo "TEST FALLITI: il bot resta alla versione di prima."
    git checkout --quiet -
    exit 1
}
echo "== Test passati: avvio della versione $VERSIONE =="
cd server
VERSIONE="$VERSIONE" docker compose up -d --build
docker compose ps
echo "Fatto. Log: cd /opt/bot-fatture/codice/server && docker compose logs -f"
