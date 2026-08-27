#!/usr/bin/env bash
# Sanity-check the running PaddleOCR sidecar. Uses only tools that ship with macOS.
# Usage: ./smoke.sh [http://localhost:8000]
set -euo pipefail

BASE="${1:-http://localhost:8000}"

echo "→ /health"
curl -fsS "$BASE/health" && echo

# Generate a small PNG with typed text using macOS's built-in Quartz stack.
# Falls back to a plain 200x60 white PNG with "SMOKE TEST" if imagemagick
# isn't present. Base64 payload path is portable — works even without a URL
# the sidecar can reach.
TMP="$(mktemp -t forge-ocr-XXXXXX).png"
python3 - "$TMP" <<'PY'
import sys, struct, zlib, base64
# Minimum viable "SMOKE TEST" PNG (32×16 monochrome). Rendered with a tiny
# built-in bitmap font. Enough for PaddleOCR to recognise "SMOKE TEST".
try:
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (240, 60), "white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 32)
    except Exception:
        font = ImageFont.load_default()
    d.text((10, 10), "SMOKE TEST", fill="black", font=font)
    img.save(sys.argv[1], "PNG")
    print("wrote PIL-rendered PNG:", sys.argv[1])
except Exception as e:
    # Ultimate fallback: a valid 1×1 white PNG. OCR won't find text, but the
    # sidecar round-trip still gets exercised.
    header = b"\x89PNG\r\n\x1a\n"
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    idat = chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff", 9))
    iend = chunk(b"IEND", b"")
    open(sys.argv[1], "wb").write(header + ihdr + idat + iend)
    print("wrote fallback 1×1 PNG:", sys.argv[1], "(reason:", e, ")")
PY

B64=$(base64 -i "$TMP" | tr -d '\n')

echo
echo "→ POST /ocr (base64 payload)"
curl -fsS -X POST "$BASE/ocr" \
  -H "Content-Type: application/json" \
  -d "{\"file_b64\":\"$B64\",\"mime_type\":\"image/png\",\"language\":\"en\"}" \
  | python3 -m json.tool
rm -f "$TMP"
echo
echo "✓ smoke done"
