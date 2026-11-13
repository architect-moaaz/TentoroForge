#!/usr/bin/env bash
# VALIDATION HELPER (run by a person on the server, after `docker compose up -d`; changes nothing).
# Checks that the backend container cannot open the tunnel's raw ports and that the gateway lets through only the two read-only routes.
#   bash src/deploy/ec2/check-tunnel-isolation.sh        (from /home/ec2-user/ttf)
# For the conclusive part, have one computer connected through Watch live first (so at least one tunnel port is listening).
cd "${TTF_DIR:-/home/ec2-user/ttf}" || exit 2
fail=0
ok()  { echo "  ok    $*"; }
bad() { echo "  FAIL  $*"; fail=1; }
# prints the HTTP status the backend container gets for: METHOD URL ("conn-refused" when it cannot connect at all)
status() {
  docker compose exec -T backend python -c "
import sys, urllib.request, urllib.error
req = urllib.request.Request(sys.argv[2], method=sys.argv[1])
try:
    print(urllib.request.urlopen(req, timeout=5).status)
except urllib.error.HTTPError as e:
    print(e.code)
except Exception:
    print('conn-refused')
" "$1" "$2" 2>/dev/null | tr -d '\r'
}
expect() {  # expect <what> <method> <url> <status...>
  what=$1; m=$2; u=$3; shift 3; got=$(status "$m" "$u")
  for w in "$@"; do [ "$got" = "$w" ] && { ok "$what -> $got"; return; }; done
  bad "$what -> $got (wanted: $*)"
}

echo "1. the gateway refuses everything but the two read-only routes (404 = refused; 502 = allowed, but nothing is listening on that port)"
G=http://tunnel:8080
expect "unknown path"                  GET  "$G/"                                  404
expect "other app route"               GET  "$G/t/22001/api/agent/chat"            404
expect "POST to the debug route"       POST "$G/t/22001/api/agent/debug"           404
expect "path climbing out"             GET  "$G/t/22001/api/agent/debug/../chat"   404
expect "encoded path climbing out"     GET  "$G/t/22001/api/agent/debug%2f..%2fchat" 404
expect "port outside 22000-22999"      GET  "$G/t/3001/api/agent/debug"            404
expect "port 22 (sshd itself)"         GET  "$G/t/22/api/agent/debug"              404
expect "the debug route (allowed)"     GET  "$G/t/22999/api/agent/debug"           502
expect "the insights route (allowed)"  GET  "$G/t/22999/api/agent/insights"        502
expect "up-check, nobody on the port"  GET  "$G/up/22999"                          404

echo "2. the ports sshd opened are on 127.0.0.1 only, and the backend cannot connect to them"
listening=$(docker compose exec -T tunnel netstat -ltn 2>/dev/null | tr -d '\r' | awk '$6=="LISTEN"{n=split($4,a,":"); p=a[n]; if (p>=22000 && p<=22999) print $4}')
if [ -z "$listening" ]; then
  echo "  (no computer is connected right now: connect one through Watch live and run this again for the conclusive check)"
else
  for addr in $listening; do
    port=${addr##*:}
    case "$addr" in
      127.0.0.1:*|::1:*) ok "port $port listens on loopback only ($addr)";;
      *) bad "port $port listens on $addr (must be 127.0.0.1)";;
    esac
    r=$(docker compose exec -T backend python -c "
import socket, sys
try:
    socket.create_connection(('tunnel', int(sys.argv[1])), timeout=3); print('CONNECTED')
except OSError:
    print('refused')
" "$port" 2>/dev/null | tr -d '\r')
    [ "$r" = "refused" ] && ok "backend cannot open tunnel:$port" || bad "backend CAN open tunnel:$port"
    expect "up-check for connected port $port" GET "$G/up/$port" 200
  done
fi

echo "3. the key-reading user is not root"
u=$(docker compose exec -T tunnel sh -c "grep -i '^AuthorizedKeysCommandUser' /etc/ssh/sshd_config" | tr -d '\r')
case "$u" in *root*) bad "$u";; *ttf-keys*) ok "$u";; *) bad "unexpected: $u";; esac
docker compose exec -T tunnel su-exec ttf-keys sh -c 'cat /keys/registry.json >/dev/null 2>&1' \
  && bad "ttf-keys can read registry.json (it holds the debug secrets)" || ok "ttf-keys cannot read registry.json"
docker compose exec -T tunnel su-exec ttf-keys /usr/local/bin/ttf-authkeys tunnel "ssh-ed25519 TESTKEY" >/dev/null \
  && ok "ttf-keys can run the key command" || bad "ttf-keys cannot run the key command"
docker compose exec -T tunnel sh -c 'ls -ld /run/ttf-sessions; ls -l /run/ttf-sessions' | tr -d '\r' | sed 's/^/        /'
# (the test note it just wrote is named after a process that does not exist, so ttf-reaper removes it within a few seconds)

exit $fail
