#!/usr/bin/env bash
# a-whole-unit-paypal-payment-is-paid.test.mts — the SHIPPED payments ledger:
# a PayPal payment in HUF/JPY/TWD is compared as PayPal was sent it.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-transform-types --no-warnings "$DIR/a-whole-unit-paypal-payment-is-paid.test.mts"
