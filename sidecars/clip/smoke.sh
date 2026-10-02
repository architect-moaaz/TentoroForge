#!/usr/bin/env bash
# Sanity-check the running CLIP sidecar: an image and two captions, and the
# caption that describes the image must be the closer one.
# Usage: ./smoke.sh [http://localhost:8001]
set -euo pipefail

BASE="${1:-http://localhost:8001}"

echo "→ /health"
curl -fsS "$BASE/health" && echo

python3 - "$BASE" <<'PY'
import base64, io, json, sys, struct, zlib, urllib.request

base = sys.argv[1]

def png(w, h, rgb):
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))

def embed(body):
    req = urllib.request.Request(base + "/embed", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    out = json.load(urllib.request.urlopen(req))
    assert out["dimensions"] == 512, out["dimensions"]
    return out["vector"]

red = embed({"image_b64": base64.b64encode(png(64, 64, (220, 20, 20))).decode(), "mime_type": "image/png"})
said_red = embed({"text": "a plain red square"})
said_blue = embed({"text": "a plain blue square"})
dot = lambda a, b: sum(x * y for x, y in zip(a, b))
print(f"red image · 'red'  = {dot(red, said_red):.3f}")
print(f"red image · 'blue' = {dot(red, said_blue):.3f}")
assert dot(red, said_red) > dot(red, said_blue), "the red caption should be closer"
print("✓ smoke done")
PY
