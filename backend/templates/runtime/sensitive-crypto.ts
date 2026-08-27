/**
 * Slice-4 encrypt-at-rest helper — AES-GCM over Node's WebCrypto.
 *
 * Every string flagged `sensitive: true` in the plan is stored in
 * `<column>_encrypted` as a base64 blob of:
 *
 *     [ 12-byte random IV ] [ ciphertext + 16-byte GCM auth tag ]
 *
 * A random IV per encrypt is REQUIRED (AES-GCM key+IV reuse leaks the
 * xor of the two plaintexts + defeats the auth tag). We generate it via
 * `crypto.getRandomValues` and prepend it to the ciphertext, matching the
 * shape every popular encrypt-at-rest guide uses.
 *
 * The encryption key comes from process.env.SENSITIVE_ENCRYPTION_KEY —
 * base64 of exactly 32 raw bytes (AES-256). runtime_injector auto-
 * generates one at first generation when the plan uses sensitive
 * columns and the org hasn't set its own; the user can rotate later by
 * pasting a new key on /settings/integrations.
 *
 * TODO(sensitive-rotation): state-of-the-art key rotation requires a
 * versioned key ID stored PER ROW (so old rows keep decrypting under
 * the previous key while new rows use the current one). Out of scope
 * for Slice 4; the current shape is upgradeable — the base64 blob can
 * be re-formatted to `[ version-byte ] [ iv ] [ ct ]` without a schema
 * change, and this helper is the only place that reads the format.
 */

import { webcrypto as _webcrypto } from "node:crypto";

// Node ≥ 20 has crypto.webcrypto; browsers have crypto directly. Pick
// whichever exists so this file compiles in either environment. Tests
// import this module directly (Node runtime), production reads it on
// the server (Node runtime) — there is currently no client-side path.
const _crypto: Crypto =
  (typeof globalThis !== "undefined" && (globalThis as any).crypto) ||
  (_webcrypto as unknown as Crypto);

const IV_BYTES = 12;   // AES-GCM canonical IV size.
const KEY_BYTES = 32;  // AES-256.

// Reuse the imported CryptoKey across calls — subtle.importKey is cheap
// but not free, and every write path calls encrypt.
let _keyCache: CryptoKey | null = null;
let _keyCacheSource: string | null = null;

function base64ToBytes(b64: string): Uint8Array {
  // Buffer is a Node built-in and unambiguously handles both standard and
  // URL-safe base64. Falls back to atob in a browser bundle.
  if (typeof Buffer !== "undefined") return new Uint8Array(Buffer.from(b64, "base64"));
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

function bytesToBase64(bytes: Uint8Array): string {
  if (typeof Buffer !== "undefined") return Buffer.from(bytes).toString("base64");
  let bin = "";
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin);
}

async function getKey(): Promise<CryptoKey> {
  const src = process.env.SENSITIVE_ENCRYPTION_KEY || "";
  if (!src) {
    // Loud + explicit: refusing to write a sensitive column with no key is
    // safer than silently writing plaintext or an all-zero-key ciphertext.
    throw new Error(
      "SENSITIVE_ENCRYPTION_KEY is not set. Sensitive columns cannot be " +
      "written or read. Set it in the environment or on /settings/integrations."
    );
  }
  if (_keyCache && _keyCacheSource === src) return _keyCache;

  const raw = base64ToBytes(src);
  if (raw.length !== KEY_BYTES) {
    throw new Error(
      `SENSITIVE_ENCRYPTION_KEY must decode to exactly ${KEY_BYTES} bytes ` +
      `(AES-256); got ${raw.length}.`
    );
  }
  _keyCache = await _crypto.subtle.importKey(
    "raw",
    raw as unknown as BufferSource,
    { name: "AES-GCM" },
    false,
    ["encrypt", "decrypt"],
  );
  _keyCacheSource = src;
  return _keyCache;
}

/** Encrypt a UTF-8 string. The IV is generated fresh per call and prepended
 *  to the ciphertext, so two encrypts of the same plaintext yield distinct
 *  outputs (proves IV randomness — the test suite asserts this). */
export async function encryptSensitive(plaintext: string): Promise<string> {
  const key = await getKey();
  const iv = new Uint8Array(IV_BYTES);
  _crypto.getRandomValues(iv);
  const enc = new TextEncoder().encode(plaintext);
  const ct = new Uint8Array(
    await _crypto.subtle.encrypt(
      { name: "AES-GCM", iv: iv as unknown as BufferSource },
      key,
      enc as unknown as BufferSource,
    ),
  );
  // Concat IV | ciphertext into a single base64 blob.
  const out = new Uint8Array(iv.length + ct.length);
  out.set(iv, 0);
  out.set(ct, iv.length);
  return bytesToBase64(out);
}

/** Decrypt a blob produced by encryptSensitive. Throws on tamper (GCM
 *  auth tag mismatch) — callers should catch + treat as a data-integrity
 *  incident, not a "value not found". */
export async function decryptSensitive(blob: string): Promise<string> {
  const key = await getKey();
  const bytes = base64ToBytes(blob);
  if (bytes.length < IV_BYTES + 1) {
    throw new Error("sensitive blob is too short — malformed or truncated");
  }
  const iv = bytes.subarray(0, IV_BYTES);
  const ct = bytes.subarray(IV_BYTES);
  const pt = new Uint8Array(
    await _crypto.subtle.decrypt(
      { name: "AES-GCM", iv: iv as unknown as BufferSource },
      key,
      ct as unknown as BufferSource,
    ),
  );
  return new TextDecoder().decode(pt);
}

// ─── Masking ─────────────────────────────────────────────────────────────

/** Fixed prefix the runtime uses to recognise "this is a masked value —
 *  don't re-encrypt as if it were fresh plaintext" on the write path.
 *  Exported so the data engine can share the same constant. */
export const MASK_PREFIX = "••••";  // "••••"

export type MaskKind = "last4" | "email" | "phone" | "full";

/** Compute a stable masked display value from a raw string. Pure — no
 *  crypto, no async — so it's cheap to call on every write.
 *
 *  Never returns the original characters beyond what the mask kind
 *  explicitly reveals. `last4` on a 3-char input yields ••••, not the
 *  3 chars themselves.
 */
export function mask(value: string, kind: MaskKind): string {
  const raw = value == null ? "" : String(value);
  if (!raw) return "";
  switch (kind) {
    case "full":
      // A fixed 8 bullets — reveals nothing about the original length.
      return "•".repeat(8);
    case "last4": {
      const tail = raw.slice(-4);
      if (tail.length < 4) return MASK_PREFIX;  // too short to reveal
      return MASK_PREFIX + tail;
    }
    case "email": {
      // Keep first char + domain. `alice@corp.com` → `a•••@corp.com`.
      const at = raw.indexOf("@");
      if (at <= 0) return MASK_PREFIX;
      const head = raw[0];
      return `${head}•••${raw.slice(at)}`;
    }
    case "phone": {
      // Show last 4 digits only. Strips non-digits before slicing so
      // formatted inputs (+1 (415) 555-1234) still land on 1234.
      const digits = raw.replace(/\D/g, "");
      const tail = digits.slice(-4);
      if (tail.length < 4) return MASK_PREFIX;
      return MASK_PREFIX + tail;
    }
    default: {
      // Unknown mask kind — degrade to full-mask rather than leak.
      return "•".repeat(8);
    }
  }
}

/** True when the given string looks like a mask emitted by `mask()`. Used
 *  by the data engine's write path to skip re-encrypting a value that was
 *  round-tripped from the read path (e.g. an edit form pre-filled with
 *  the masked value and submitted unchanged). Cheap prefix check — the
 *  bullet char isn't a legitimate character in any real account/SSN/etc.
 */
export function looksMasked(value: unknown): boolean {
  if (typeof value !== "string" || !value) return false;
  return value.startsWith("•") || value.includes("•••");
}
