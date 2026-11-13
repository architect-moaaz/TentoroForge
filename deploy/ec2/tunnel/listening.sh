#!/bin/sh
# Publishes which tunnel ports have a computer connected right now: one empty-ish file per port in /run/ttf-up, which the
# gateway serves as /up/<port>. The platform backend can no longer open the raw ports to see whether anyone is listening
# (they are bound on 127.0.0.1 inside this container), so it asks the gateway, and the gateway answers from this list.
# A port listens exactly as long as its builder's SSH session lives. Looked at every 2 seconds.
DIR=/run/ttf-up
mkdir -p "$DIR"
while sleep 2; do
  # local address is column 4 ("127.0.0.1:22001" or "::1:22001"); keep only the tunnel range
  ports=$(netstat -ltn 2>/dev/null | awk '$6=="LISTEN"{n=split($4,a,":"); p=a[n]; if (p>=22000 && p<=22999) print p}' | sort -u)
  for p in $ports; do [ -e "$DIR/$p" ] || echo up > "$DIR/$p"; done
  for f in "$DIR"/*; do
    [ -e "$f" ] || continue
    echo "$ports" | grep -qx "${f##*/}" || rm -f "$f"
  done
done
