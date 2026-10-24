/**
 * Connecting the computer where the app runs, when TentoroForge is on a server. No React, no network.
 *
 * The server cannot see the builder's localhost, so the builder runs a small connector on the computer where the app runs; it
 * opens a reverse SSH tunnel to the server (services/agent_tunnel.py). This file says what that looks like on screen: the
 * commands to run, how long a code lasts, and what state the tunnel is in, in plain words.
 */

/** What the platform says about the tunnel (never the secret). */
export interface TunnelState {
  enabled: boolean;
  registered: boolean;
  connected: boolean;
  port?: number;
  appPort?: number | null;
  clientIp?: string | null;
  label?: string | null;
  pairedAt?: number | null;
  hosted?: { vercel?: { url?: string | null; environment?: string | null } };
}

export const NO_TUNNEL: TunnelState = { enabled: false, registered: false, connected: false };

export interface Pairing {
  code: string;
  /** Seconds since 1970. */
  expiresAt: number;
}

/** A value from the platform as a tunnel state, whatever it sent. */
export function asTunnelState(raw: unknown): TunnelState {
  const r = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : undefined);
  const text = (v: unknown) => (typeof v === "string" && v ? v : null);
  const hosted = r.hosted && typeof r.hosted === "object" ? (r.hosted as TunnelState["hosted"]) : undefined;
  return {
    enabled: r.enabled === true,
    registered: r.registered === true,
    connected: r.connected === true,
    port: num(r.port),
    appPort: num(r.appPort) ?? null,
    clientIp: text(r.clientIp),
    label: text(r.label),
    pairedAt: num(r.pairedAt) ?? null,
    ...(hosted ? { hosted } : {}),
  };
}

/** The one command to paste where the app runs. `origin` is the address of TentoroForge as the builder's browser has it. */
export function connectorCommands(origin: string, code: string, appPort: number): { unix: string; windows: string } {
  const base = origin.replace(/\/+$/, "");
  const run = `node ttf-watch-connect.mjs --server ${base} --code ${code} --app ${appPort}`;
  return {
    unix: `curl -fsSL ${base}/api/tunnel/connector.mjs -o ttf-watch-connect.mjs && ${run}`,
    windows: `Invoke-WebRequest ${base}/api/tunnel/connector.mjs -OutFile ttf-watch-connect.mjs; ${run}`,
  };
}

/** A port as typed: a whole number from 1 to 65535, else null. */
export function validPort(text: string): number | null {
  if (!/^\d{1,5}$/.test(text.trim())) return null;
  const n = Number(text);
  return n >= 1 && n <= 65535 ? n : null;
}

/** Seconds left on a code, never negative, rounded up so a code never reads 0:00 while it still works. */
export const secondsLeft = (p: Pairing, nowMs: number): number => Math.max(0, Math.ceil(p.expiresAt - nowMs / 1000));

export function clock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export interface Summary {
  tone: "idle" | "good" | "warn";
  text: string;
}

/** The tunnel in a sentence: what the builder should know right now. */
export function summarise(t: TunnelState): Summary {
  if (!t.registered) return { tone: "idle", text: "No computer connected yet." };
  const who = t.label ? `${t.label}${t.clientIp ? ` (${t.clientIp})` : ""}` : t.clientIp ?? "your computer";
  if (!t.connected) return { tone: "warn", text: `${who} is paired but not connected right now. Run the connector again: it reconnects by itself after that.` };
  return { tone: "good", text: `Connected: ${who}${t.appPort ? `, app on port ${t.appPort}` : ""}.` };
}
