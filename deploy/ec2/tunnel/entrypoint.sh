#!/bin/sh
set -e
# The server's identity is made once and kept, so connectors that pinned it never see it change.
mkdir -p /hostkeys
[ -f /hostkeys/ssh_host_ed25519_key ] || ssh-keygen -q -t ed25519 -N "" -C ttf-tunnel -f /hostkeys/ssh_host_ed25519_key
chmod 600 /hostkeys/ssh_host_ed25519_key
# Publish the public half where the platform can read it: connectors are told to trust exactly this key.
cp /hostkeys/ssh_host_ed25519_key.pub /keys/host_key.pub
chmod 644 /keys/host_key.pub
[ -f /keys/authorized_keys ] || { : > /keys/authorized_keys; chmod 644 /keys/authorized_keys; }
# Notes of which key each connection used: written by the unprivileged AuthorizedKeysCommand user, read and removed by the reaper (root).
rm -rf /run/ttf-sessions && mkdir -p /run/ttf-sessions
chown ttf-keys:ttf-keys /run/ttf-sessions && chmod 700 /run/ttf-sessions
/usr/local/bin/ttf-reaper &
# Which ports have a computer connected, for the gateway to answer /up/<port>. Readable by the gateway's user.
rm -rf /run/ttf-up && mkdir -p /run/ttf-up && chmod 755 /run/ttf-up
/usr/local/bin/ttf-listening &
# The gateway runs as its own user and is started again if it ever stops (sshd below is the container's main process).
( while :; do
    su-exec ttf-gw env XDG_DATA_HOME=/tmp/caddy-data XDG_CONFIG_HOME=/tmp/caddy-config \
      caddy run --config /etc/ttf-gateway.Caddyfile --adapter caddyfile || true
    echo "gateway stopped; starting it again"; sleep 2
  done ) &
exec /usr/sbin/sshd -D -e
