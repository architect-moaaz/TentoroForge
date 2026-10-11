#!/usr/bin/env bash
# The SHIPPED pwa/sw.js keeps the shell and never the data; push.ts signs
# with the app's keys and forgets gone devices.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-strip-types --no-warnings "$DIR/the-service-worker-keeps-the-shell-never-the-data.test.mts"
node --experimental-strip-types --no-warnings "$DIR/a-notification-reaches-a-subscribed-device.test.mts"
