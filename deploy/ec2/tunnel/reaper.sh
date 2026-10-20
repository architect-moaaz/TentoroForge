#!/bin/sh
# Closes the connection of a computer the platform no longer lists.
#
# sshd checks the key list only when a connection is made, so removing a computer from a project would leave its connection (and
# its port) open until the laptop drops it, and a new computer could not take the port over. ttf-authkeys notes, per connection
# (named by its sshd process), which key was used. Every few seconds this looks for notes whose key is no longer in the list and
# ends those connections. The connector then reconnects, is refused, and tells its owner the computer was removed.
# A list that cannot be read is never taken to mean "remove everyone".
KEYS=/keys/authorized_keys
DIR=/run/ttf-sessions

while sleep 5; do
  [ -r "$KEYS" ] || continue
  cat "$KEYS" > /dev/null 2>&1 || continue
  for note in "$DIR"/*; do
    [ -f "$note" ] || continue
    pid=${note##*/}
    # The connection is gone (or the number now belongs to something else): drop the note.
    if ! grep -q sshd "/proc/$pid/cmdline" 2>/dev/null; then rm -f "$note"; continue; fi
    key=$(cat "$note" 2>/dev/null)
    [ -n "$key" ] || continue
    if ! grep -qF " $key " "$KEYS" 2>/dev/null; then
      kill "$pid" 2>/dev/null && echo "reaper: closed a connection whose key is no longer in the key list (sshd $pid)"
      rm -f "$note"
    fi
  done
done
