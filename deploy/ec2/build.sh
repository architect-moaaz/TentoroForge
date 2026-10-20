#!/usr/bin/env bash
# Builds the two images with an ISOLATED builder ("ttfbuild": its own cache, removed at the end), one image at a time,
# with the disk watched: a watchdog stops the build if free space drops below 2000 MB.
set -uo pipefail
cd /home/ec2-user/ttf
STOP_MB=2000
free_mb() { df --output=avail -BM / | tail -1 | tr -dc '0-9'; }
say() { echo "[$(date -u +%H:%M:%S)] [disk $(free_mb) MB free] $*"; }

( while sleep 2; do
    f=$(free_mb)
    if [ "$f" -lt "$STOP_MB" ]; then
      echo "WATCHDOG: only $f MB free (stop line $STOP_MB): stopping the build"
      docker buildx stop ttfbuild >/dev/null 2>&1
      pkill -f "buildx build" 2>/dev/null
      exit 0
    fi
  done ) &
WD=$!
cleanup() { kill "$WD" 2>/dev/null; docker buildx rm ttfbuild >/dev/null 2>&1; say "builder and its cache removed"; }
trap cleanup EXIT

# Each rebuild leaves the previous image behind with no name; those are never used by a running container, so clear them first.
docker image prune -f >/dev/null 2>&1
[ "$(free_mb)" -ge 4000 ] || { say "ABORT: less than 4000 MB free before starting"; exit 3; }
docker buildx inspect ttfbuild >/dev/null 2>&1 || docker buildx create --name ttfbuild --driver docker-container >/dev/null
say "builder ready"

if [ "${1:-all}" = "all" ] || [ "${1:-}" = "frontend" ]; then
  say "building the frontend"
  docker buildx build --builder ttfbuild --load --progress=plain -t ttf-frontend:1 \
    -f src/frontend/Dockerfile.prod --build-arg NEXT_PUBLIC_API_URL="" --build-arg NEXT_PUBLIC_PREVIEW_URL="" src || { say "FRONTEND BUILD FAILED"; exit 1; }
  say "frontend built; clearing its scratch space"
  docker buildx prune --builder ttfbuild -af >/dev/null 2>&1
fi
if [ "${1:-all}" = "all" ] || [ "${1:-}" = "tunnel" ]; then
  say "building the tunnel service"
  docker buildx build --builder ttfbuild --load --progress=plain -t ttf-tunnel:1 src/deploy/ec2/tunnel || { say "TUNNEL BUILD FAILED"; exit 1; }
fi
if [ "${1:-all}" = "all" ] || [ "${1:-}" = "backend" ]; then
  say "building the backend"
  docker buildx build --builder ttfbuild --load --progress=plain -t ttf-backend:1 src/backend || { say "BACKEND BUILD FAILED"; exit 1; }
  say "backend built"
fi
docker images --format "{{.Repository}}:{{.Tag}}  {{.Size}}" | grep "^ttf-"
say "BUILD OK"
