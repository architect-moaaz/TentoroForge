#!/bin/bash
# Cut the forge-v3 stack over to the staged tree, in place — THE ONLY WAY A
# RUNNING STACK IS RESTARTED.
#   /opt/tentoro-forge-v3-new  (git archive + dists, images already built there)
#   /opt/tentoro-forge-v3      (the live stack; compose project `tentoro-forge-v3`)
#
# THE GATE IS NOT NEGOTIABLE. On 2026-10-15 at 07:39 UTC the stack was
# recreated by hand while this script was reporting "busy: pcn4owv7" every
# minute: a tester's 54-minute turn died and the chat stayed on "Still
# working on it". There is no force flag and no environment variable that
# skips the gate; a cutover that cannot wait is a cutover that waits. If you
# find yourself typing `docker compose up -d` in /opt/tentoro-forge-v3 while
# a ledger is alive, stop: the person on the other end is mid-turn.
#
# Installed on the host as ~/v3-cutover.sh from deploy/v3-cutover.sh in the
# repository; change it there.
set -u
EX="--exclude=/data --exclude=/.env --exclude=/a2ui --exclude=/logs --exclude=/node_modules --exclude=/frontend/node_modules --exclude=/frontend/.next --exclude=/packages/*/node_modules --exclude=/apps/*/node_modules --exclude=/apps/*/.next"
#: A ledger that wrote within this many seconds is alive. Turns heartbeat
#: every 20 s, builds on every event; three minutes covers a long model call.
BUSY_S=180

busy() {
  ( cd /opt/tentoro-forge-v3/data/output || exit 0
  now=$(date +%s)
  for d in */; do
    for f in "$d.forge/runs/"*.jsonl; do
      [ -f "$f" ] || continue
      if ! tail -1 "$f" | grep -q "run:end\|run:crashed"; then
        age=$((now - $(stat -c %Y "$f")))
        if [ "$age" -lt "$BUSY_S" ]; then echo "[$(date -u +%T)] busy: $d$(basename "$f" .jsonl) (${age}s since its last heartbeat)"; exit 1; fi
      fi
    done
  done
  # Review copies of an app's database in use are a check mid-flight.
  n=$(docker exec tentoro-forge-v3-apps-db-1 psql -U postgres -At -c "select count(*) from pg_stat_activity where datname like '%_review_%' or datname like '%_trial%'" 2>/dev/null || echo 0)
  if [ "${n:-0}" != "0" ]; then echo "[$(date -u +%T)] busy: $n review/trial database(s) in use"; exit 1; fi
  exit 0 )
}

if ! grep -q STAGE-BUILD-DONE /tmp/v3-stage-build.log 2>/dev/null; then echo "staged image build not finished"; exit 2; fi
if grep -q STAGE-BUILD-FAILED /tmp/v3-stage-build.log; then echo "staged image build FAILED; nothing touched"; exit 2; fi
busy || { echo "v3 is busy; nothing touched"; exit 3; }

echo "[$(date -u +%T)] syncing the tree"
rsync -a --delete $EX /opt/tentoro-forge-v3-new/ /opt/tentoro-forge-v3/ || { echo "rsync failed"; exit 4; }
cd /opt/tentoro-forge-v3
echo "[$(date -u +%T)] tree at $(cat .forge-version); re-tagging images under the live project name"
docker compose -f docker-compose.prod.yml build > /tmp/v3-live-build.log 2>&1 || { echo "live build failed (see /tmp/v3-live-build.log)"; exit 5; }
# The gate again, right before the restart: a turn can start during the re-tag.
busy || { echo "v3 became busy during the re-tag; tree is synced, images built, stack NOT restarted — rerun to finish"; exit 3; }
echo "[$(date -u +%T)] bringing the stack up"
# NOT THE COMPOSE FILE'S CADDY: the old stack's Caddy owns :80/:443 and routes this stack.
docker compose -f docker-compose.prod.yml up -d backend frontend render-scaffold forge-verify postgres redis apps-db || { echo "up failed"; exit 6; }
sleep 25
docker compose -f docker-compose.prod.yml ps --format "{{.Name}}\t{{.Status}}"
echo "[$(date -u +%T)] CUTOVER-DONE"
