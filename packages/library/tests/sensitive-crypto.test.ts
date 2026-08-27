/**
 * Slice-4 encrypt-at-rest: round-trip + IV-randomness contract.
 *
 * The sensitive-column helper is a template that ships into every generated
 * app under `src/lib/sensitive-crypto.ts`. Its correctness is load-bearing:
 * a broken IV would silently reduce AES-GCM to a stream cipher whose
 * plaintext xor of two encrypted values would leak. These tests import
 * directly from the template file so a regression at the source is caught
 * before the copy fans out to every app.
 */
import { describe, it, expect, beforeAll } from "vitest";
import {
  encryptSensitive,
  decryptSensitive,
  mask,
  looksMasked,
  MASK_PREFIX,
} from "../../../backend/templates/runtime/sensitive-crypto";

// A stable 32-byte AES-256 key — random bytes generated once and fixed
// here so the tests are deterministic. Never used outside this file.
const TEST_KEY_B64 = Buffer.from(
  new Uint8Array(32).map((_, i) => (i * 37 + 11) & 0xff),
).toString("base64");

beforeAll(() => {
  process.env.SENSITIVE_ENCRYPTION_KEY = TEST_KEY_B64;
});


describe("encryptSensitive / decryptSensitive", () => {
  it("round-trips arbitrary plaintext", async () => {
    for (const pt of [
      "hello world",
      "1234-5678-9012-3456",           // credit card
      "123-45-6789",                    // SSN
      "email+tag@example.com",
      "unicode: 你好 مرحبا 🔒",
      "",                                // empty string
      "x".repeat(1024),                  // 1KB
    ]) {
      const blob = await encryptSensitive(pt);
      const back = await decryptSensitive(blob);
      expect(back).toBe(pt);
    }
  });

  it("emits distinct ciphertexts for the SAME plaintext (proves IV randomness)", async () => {
    const pt = "1234-5678-9012-3456";
    const ct1 = await encryptSensitive(pt);
    const ct2 = await encryptSensitive(pt);
    expect(ct1).not.toBe(ct2);
    // Both still decrypt back to the same plaintext.
    expect(await decryptSensitive(ct1)).toBe(pt);
    expect(await decryptSensitive(ct2)).toBe(pt);
  });

  it("prepends a 12-byte IV to the ciphertext", async () => {
    const blob = await encryptSensitive("abcdef");
    const bytes = Buffer.from(blob, "base64");
    // 12-byte IV + at least 6 bytes of plaintext + 16-byte GCM tag.
    expect(bytes.length).toBeGreaterThanOrEqual(12 + 6 + 16);
  });

  it("rejects a tampered blob (GCM auth tag)", async () => {
    const blob = await encryptSensitive("original");
    const bytes = Buffer.from(blob, "base64");
    // Flip the last byte (in the GCM auth-tag region) → decryption must throw.
    bytes[bytes.length - 1] ^= 0x01;
    const tampered = bytes.toString("base64");
    await expect(decryptSensitive(tampered)).rejects.toBeDefined();
  });

  it("throws a helpful error when SENSITIVE_ENCRYPTION_KEY is missing", async () => {
    const saved = process.env.SENSITIVE_ENCRYPTION_KEY;
    delete process.env.SENSITIVE_ENCRYPTION_KEY;
    try {
      await expect(encryptSensitive("x")).rejects.toThrow(/SENSITIVE_ENCRYPTION_KEY/);
    } finally {
      process.env.SENSITIVE_ENCRYPTION_KEY = saved;
    }
  });

  it("throws when the key is the wrong length", async () => {
    const saved = process.env.SENSITIVE_ENCRYPTION_KEY;
    // 16 bytes — legal AES-128 key length but we require AES-256.
    process.env.SENSITIVE_ENCRYPTION_KEY = Buffer.alloc(16, 0x42).toString("base64");
    try {
      await expect(encryptSensitive("x")).rejects.toThrow(/32 bytes/);
    } finally {
      process.env.SENSITIVE_ENCRYPTION_KEY = saved;
    }
  });
});


describe("mask()", () => {
  it("last4 keeps only the last 4 chars behind the bullet prefix", () => {
    expect(mask("1234567890123456", "last4")).toBe("••••3456");
    expect(mask("abc", "last4")).toBe(MASK_PREFIX);   // too short → nothing revealed
  });

  it("full always returns 8 bullets — no length or content leaks", () => {
    expect(mask("123-45-6789", "full")).toBe("••••••••");
    expect(mask("x", "full")).toBe("••••••••");
    expect(mask("very long secret string", "full")).toBe("••••••••");
  });

  it("email keeps first char + domain", () => {
    expect(mask("alice@corp.com", "email")).toBe("a•••@corp.com");
    // No @ → degrade to plain mask; never leaks the input.
    expect(mask("no-at-sign", "email")).toBe(MASK_PREFIX);
  });

  it("phone slices only the digit tail", () => {
    expect(mask("+1 (415) 555-1234", "phone")).toBe("••••1234");
    expect(mask("123", "phone")).toBe(MASK_PREFIX);   // too few digits
  });

  it("empty value returns empty string (mask of nothing is nothing)", () => {
    expect(mask("", "last4")).toBe("");
    expect(mask("", "full")).toBe("");
  });
});


describe("looksMasked()", () => {
  it("recognises mask-prefixed values", () => {
    expect(looksMasked("••••1234")).toBe(true);
    expect(looksMasked("••••••••")).toBe(true);
    expect(looksMasked("a•••@corp.com")).toBe(true);
  });
  it("does NOT recognise plain values", () => {
    expect(looksMasked("1234567890123456")).toBe(false);
    expect(looksMasked("")).toBe(false);
    expect(looksMasked(undefined)).toBe(false);
    expect(looksMasked(null)).toBe(false);
    expect(looksMasked(1234)).toBe(false);
  });
});
