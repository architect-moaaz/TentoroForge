#!/bin/sh
# Called by sshd with the user name and the key being offered: print that user's authorized keys. Only "tunnel" has any, and the
# list is the platform's (written atomically to /keys/authorized_keys). No file, no keys, no way in.
#
# It also notes which key this connection used, under the connection's own sshd process, so ttf-reaper can end the connection
# when the platform removes that key (sshd itself only reads the list while a connection is being made).
[ "$1" = "tunnel" ] || exit 0
[ -r /keys/authorized_keys ] || exit 0
[ -n "$2" ] && printf '%s' "$2" > "/run/ttf-sessions/$PPID" 2>/dev/null
cat /keys/authorized_keys
exit 0
