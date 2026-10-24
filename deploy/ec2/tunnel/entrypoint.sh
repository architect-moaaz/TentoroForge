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
rm -rf /run/ttf-sessions && mkdir -p /run/ttf-sessions
/usr/local/bin/ttf-reaper &
exec /usr/sbin/sshd -D -e
