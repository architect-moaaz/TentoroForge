#!/usr/bin/env node
/**
 * TentoroForge Watch live connector.
 *
 * Run this on the computer where YOUR app is running. It opens a reverse SSH tunnel to the TentoroForge server, so the
 * server can watch the app's real chats even though the app only listens on this computer's localhost.
 *
 *   node ttf-watch-connect.mjs --server https://forge.example.com --code ABCD-EFGH --app 3001
 *
 * Run it from the app's folder (the one with package.json): it puts a fresh debug key there, the one the app checks.
 * It needs Node 18+ and the OpenSSH client (`ssh` and `ssh-keygen`; Windows 10+, macOS and Linux have them).
 * It holds no secret and installs nothing. Press Ctrl+C to disconnect. It reconnects by itself after a drop.
 *
 * What it does, in order, saying each step: checks the app answers here, checks it can reach the server (name -> address,
 * then the SSH port), swaps the one-time code for a connection (sending only its own PUBLIC key), writes the debug key
 * for the app, then keeps the tunnel up. Exit codes: 0 stopped by you, 2 bad input, 3 this computer's key was removed,
 * 4 the server's identity is not the one it was told to trust, 5 the port is held by another connection, 6 gave up.
 */
import { spawn, spawnSync } from "node:child_process";
import crypto from "node:crypto";
import dns from "node:dns/promises";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

export const EXIT = { OK: 0, INPUT: 2, KEY_REMOVED: 3, SERVER_IDENTITY: 4, PORT_HELD: 5, GAVE_UP: 6 };
export const HOME = path.join(os.homedir(), ".ttf-watch");

// ── arguments ───────────────────────────────────────────────────────────────

export const USAGE = `TentoroForge Watch live connector

  node ttf-watch-connect.mjs --server <url> --code <code> --app <port> [options]

  --server <url>   the TentoroForge address you use in your browser (e.g. https://forge.example.com)
  --code <code>    the one-time code Watch live shows (valid 10 minutes, works once)
  --app <port>     the port your app listens on here (e.g. 3001)
  --dir <folder>   your app's folder (default: the current folder); a fresh debug key is written there
  --label <name>   a name for this computer in Watch live (default: this computer's name)
  --no-key-file    do not write the debug key (you will copy it yourself)
  --help           this text

Everything can also be set with environment variables: TTF_SERVER, TTF_CODE, TTF_APP_PORT.`;

export function parseArgs(argv, env = {}) {
  const out = { server: env.TTF_SERVER ?? "", code: env.TTF_CODE ?? "", app: env.TTF_APP_PORT ?? "", dir: "", label: "", keyFile: true, help: false,
    // for testing against a server whose SSH port is only reachable some other way
    sshHost: "", sshPort: "" };
  const rest = [...argv];
  const need = (flag) => {
    const v = rest.shift();
    if (v === undefined || v.startsWith("--")) throw new InputError(`${flag} needs a value.`);
    return v;
  };
  while (rest.length) {
    const a = rest.shift();
    if (a === "--help" || a === "-h") out.help = true;
    else if (a === "--server") out.server = need(a);
    else if (a === "--code") out.code = need(a);
    else if (a === "--app") out.app = need(a);
    else if (a === "--dir") out.dir = need(a);
    else if (a === "--label") out.label = need(a);
    else if (a === "--no-key-file") out.keyFile = false;
    else if (a === "--ssh-host") out.sshHost = need(a);
    else if (a === "--ssh-port") out.sshPort = need(a);
    else throw new InputError(`I do not know "${a}". Run with --help to see what I accept.`);
  }
  if (out.help) return out;
  let url;
  try {
    url = new URL(out.server);
    if (url.protocol !== "http:" && url.protocol !== "https:") throw new Error("scheme");
  } catch {
    throw new InputError("--server must be the TentoroForge address, like https://forge.example.com (with http:// or https://).");
  }
  out.server = url.origin;
  out.code = String(out.code).toUpperCase().replace(/[^A-Z0-9]/g, "");
  if (out.code.length !== 8) throw new InputError("--code must be the 8-character code Watch live shows (like ABCD-EFGH).");
  const port = Number(out.app);
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new InputError("--app must be the port your app listens on, a number from 1 to 65535 (like 3001).");
  out.app = port;
  if (out.sshPort !== "" && !(Number(out.sshPort) > 0 && Number(out.sshPort) < 65536)) throw new InputError("--ssh-port must be a port number.");
  out.dir = path.resolve(out.dir || process.cwd());
  out.label = (out.label || os.hostname()).replace(/[^\w .@-]/g, "").slice(0, 64) || "computer";
  return out;
}

export class InputError extends Error {}

// ── what ssh says when it stops, and what to do about it ────────────────────

/** Sort ssh's last words into what the connector should do. `retry` means try again later by itself. */
export function classifySsh(stderr) {
  const t = String(stderr);
  if (/Permission denied \(publickey|Too many authentication failures/i.test(t)) {
    return { kind: "key-removed", fatal: true, exit: EXIT.KEY_REMOVED,
      say: "The server no longer accepts this computer's key (the pairing was removed or replaced by a newer one). Ask for a new code in Watch live and run this again." };
  }
  if (/REMOTE HOST IDENTIFICATION HAS CHANGED|Host key verification failed|host key for .* has changed/i.test(t)) {
    return { kind: "identity", fatal: true, exit: EXIT.SERVER_IDENTITY,
      say: "The server's identity is not the one this connector was told to trust, so it stopped. Do not continue unless you know why: ask for a new code in Watch live to pair again." };
  }
  if (/remote port forwarding failed|Could not request local forwarding|cannot listen to port|Address already in use/i.test(t)) {
    return { kind: "port-held", fatal: false, exit: EXIT.PORT_HELD, wait: 15,
      say: "Another connection is using this project's tunnel port. Another connector may still be running (close it), or a dead one is still being cleared by the server, which takes up to about 45 seconds." };
  }
  if (/Could not resolve hostname|Name or service not known|nodename nor servname/i.test(t)) {
    return { kind: "network", fatal: false, say: "Cannot find the server's address: check this computer's internet connection and DNS." };
  }
  if (/timed out|No route to host|Network is unreachable|Connection refused|Connection closed|Connection reset|kex_exchange_identification|Broken pipe|banner exchange|port 22\d+: |Unable to negotiate/i.test(t)) {
    return { kind: "network", fatal: false, say: "Lost the connection to the server (network down, laptop asleep, or the SSH port is blocked here). Trying again." };
  }
  return { kind: "unknown", fatal: false, say: t.trim().split("\n").slice(-2).join(" ").slice(0, 240) || "ssh stopped." };
}

/** Seconds to wait before the n-th retry (0-based): 2, 4, 8, 16, then 30 for ever. */
export const backoff = (n) => Math.min(30, 2 ** (n + 1));

// ── building the ssh command ────────────────────────────────────────────────

/** ssh reads -o values like a config file: a value with a space must be in quotes or it is cut in two. */
export function sshOpt(name, value) {
  const v = String(value).replace(/\\/g, "/");
  return `${name}=${/\s/.test(v) ? `"${v}"` : v}`;
}

export function knownHostsLine(host, port, hostKey) {
  return `${port === 22 ? host : `[${host}]:${port}`} ${hostKey}`;
}

export function sshArgs({ user, host, port, remotePort, appPort, keyFile, knownHostsFile }) {
  return [
    "-N", "-T",
    "-o", "ExitOnForwardFailure=yes",
    "-o", "ServerAliveInterval=15",
    "-o", "ServerAliveCountMax=3",
    "-o", "ConnectTimeout=10",
    "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=yes",
    "-o", sshOpt("UserKnownHostsFile", knownHostsFile),
    "-o", "IdentitiesOnly=yes",
    "-o", "PasswordAuthentication=no",
    "-o", "LogLevel=ERROR",
    "-i", keyFile,
    "-p", String(port),
    "-R", `0.0.0.0:${remotePort}:localhost:${appPort}`,
    `${user}@${host}`,
  ];
}

// ── checks ──────────────────────────────────────────────────────────────────

const say = (s) => console.log(s);
const ok = (s) => say(`  [ok] ${s}`);
const bad = (s) => say(`  [!!] ${s}`);
const info = (s) => say(`       ${s}`);

/** Can a TCP connection be made, and if not, why, in a way a person can act on. */
export function tcpCheck(host, port, timeoutMs = 6000) {
  return new Promise((resolve) => {
    const started = Date.now();
    const socket = net.connect({ host, port });
    let done = false;
    const end = (result) => {
      if (done) return;
      done = true;
      socket.destroy();
      resolve({ ...result, ms: Date.now() - started });
    };
    socket.setTimeout(timeoutMs, () => end({ ok: false, why: "timeout" }));
    socket.once("connect", () => end({ ok: true }));
    socket.once("error", (e) => end({ ok: false, why: e.code || "error", message: e.message }));
  });
}

export function explainTcp(host, port, r) {
  if (r.ok) return "";
  if (r.why === "ECONNREFUSED") return `Nothing is listening on ${host}:${port}.`;
  if (r.why === "timeout" || r.why === "ETIMEDOUT") return `No answer from ${host}:${port}: a firewall (the server's security group, or this network) is probably blocking port ${port}.`;
  if (r.why === "ENOTFOUND" || r.why === "EAI_AGAIN") return `Cannot find ${host}: check the address and this computer's internet connection.`;
  if (r.why === "EHOSTUNREACH" || r.why === "ENETUNREACH") return `No route to ${host}: this network cannot reach it.`;
  return `Could not connect to ${host}:${port} (${r.why}).`;
}

export async function localApp(port) {
  for (const host of ["127.0.0.1", "::1"]) {
    if ((await tcpCheck(host, port, 1500)).ok) return { ok: true, host };
  }
  const others = [];
  for (let p = 3000; p <= 3010; p++) if (p !== port && (await tcpCheck("127.0.0.1", p, 400)).ok) others.push(p);
  return { ok: false, others };
}

export function findTool(name) {
  const r = spawnSync(name, name === "ssh" ? ["-V"] : ["-?"], { encoding: "utf8", windowsHide: true });
  return !r.error;
}

const SSH_HELP = process.platform === "win32"
  ? "Install the OpenSSH Client: Settings > Apps > Optional features > Add a feature > OpenSSH Client."
  : "Install the OpenSSH client (for example: sudo apt install openssh-client, or it comes with macOS).";

// ── talking to TentoroForge ─────────────────────────────────────────────────

export async function postJson(url, body, opts = {}) {
  return requestJson(url, { method: "POST", body, ...opts });
}

export async function getJson(url, opts = {}) {
  return requestJson(url, { method: "GET", ...opts });
}

export async function requestJson(url, { method, body, tries = 3, timeoutMs = 15000, fetchImpl = fetch } = {}) {
  let last;
  for (let i = 0; i < tries; i++) {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), timeoutMs);
    try {
      const res = await fetchImpl(url, { method, headers: { "content-type": "application/json" }, ...(body === undefined ? {} : { body: JSON.stringify(body) }), signal: ctl.signal });
      const data = await res.json().catch(() => ({}));
      return { status: res.status, data };
    } catch (e) {
      last = e;
      if (i < tries - 1) await new Promise((r) => setTimeout(r, 1000 * (i + 1)));
    } finally {
      clearTimeout(timer);
    }
  }
  const why = last?.name === "AbortError" ? "no answer in time" : last?.cause?.code || last?.message || "network error";
  const e = new Error(`Could not reach ${url}: ${why}.`);
  e.network = true;
  throw e;
}

export function explainInfo(status, data) {
  const detail = typeof data?.detail === "string" ? data.detail : "";
  if (status === 404) return "This address answered, but it is not a TentoroForge that supports Watch live. Check the address (it is the one you open in your browser).";
  if (status === 503) return detail || "The server's tunnel service is not ready. Try again in a moment, or tell whoever runs the server.";
  return detail || `The server would not say where to connect (HTTP ${status}).`;
}

export function explainPair(status, data) {
  const detail = typeof data?.detail === "string" ? data.detail : "";
  if (status === 404) return detail || "That code is not valid, or it has expired. Ask for a new one in Watch live.";
  if (status === 429) return detail || "Too many wrong codes from this address. Wait a minute and try again.";
  if (status === 409) return detail || "This computer's key is already connected to another project. Run the connector again.";
  if (status === 503) return detail || "The server's tunnel service is not ready. Try again in a moment, or tell whoever runs the server.";
  return detail || `The server refused the pairing (HTTP ${status}).`;
}

// ── keys and files ──────────────────────────────────────────────────────────

/**
 * A fresh ed25519 key for this pairing, in a file of its own. A key belongs to one project (the server gives each project its
 * own port and honours only the first line that matches a key), so every pairing makes a new one; once the server has said
 * which project it is for, `keepKey` files it under that project's name and removes the one it replaces.
 */
export function newKey(home = HOME) {
  fs.mkdirSync(path.join(home, "keys"), { recursive: true, mode: 0o700 });
  const keyFile = path.join(home, "keys", `new-${crypto.randomBytes(6).toString("hex")}`);
  const r = spawnSync("ssh-keygen", ["-t", "ed25519", "-N", "", "-C", "ttf-watch", "-q", "-f", keyFile], { encoding: "utf8", windowsHide: true });
  if (r.status !== 0) throw new Error(`Could not make a key: ${(r.stderr || r.error?.message || "ssh-keygen failed").trim()}`);
  try { fs.chmodSync(keyFile, 0o600); } catch { /* Windows keeps its own permissions */ }
  const [type, body] = fs.readFileSync(`${keyFile}.pub`, "utf8").trim().split(/\s+/);
  if (type !== "ssh-ed25519" || !body) throw new Error("ssh-keygen did not make an ed25519 key.");
  return { keyFile, publicKey: `${type} ${body}` }; // the comment is left off: the server accepts a bare key only
}

/** File the new key under the project it was accepted for, replacing that project's earlier one. Returns the key's path. */
export function keepKey(keyFile, projectId, home = HOME) {
  const safe = String(projectId).replace(/[^A-Za-z0-9-]/g, "");
  if (!safe) return keyFile;
  const target = path.join(home, "keys", `project-${safe}`);
  for (const f of [target, `${target}.pub`]) fs.rmSync(f, { force: true });
  fs.renameSync(keyFile, target);
  fs.renameSync(`${keyFile}.pub`, `${target}.pub`);
  return target;
}

/** Keys left behind by pairings that never finished are removed, so the folder does not fill up. */
export function sweepKeys(home = HOME) {
  const dir = path.join(home, "keys");
  try {
    for (const f of fs.readdirSync(dir)) if (f.startsWith("new-")) fs.rmSync(path.join(dir, f), { force: true });
  } catch { /* nothing to sweep */ }
}

export const newSecret = () => crypto.randomBytes(32).toString("base64url");

/** Is this a TentoroForge app folder? Where the app looks for its debug key. */
export function looksLikeApp(dir) {
  try {
    const pkg = JSON.parse(fs.readFileSync(path.join(dir, "package.json"), "utf8"));
    return !!(pkg.dependencies?.next || pkg.devDependencies?.next || pkg.scripts?.dev);
  } catch {
    return false;
  }
}

export function writeSecret(dir, secret) {
  const file = path.join(dir, ".forge-debug-secret");
  fs.writeFileSync(file, secret + "\n", { mode: 0o600 });
  const gi = path.join(dir, ".gitignore");
  try {
    const text = fs.existsSync(gi) ? fs.readFileSync(gi, "utf8") : "";
    if (!text.split(/\r?\n/).includes(".forge-debug-secret")) fs.writeFileSync(gi, text.replace(/\n*$/, text ? "\n" : "") + ".forge-debug-secret\n");
  } catch { /* the key still works if the ignore file cannot be changed */ }
  return file;
}

// ── the tunnel, kept up ─────────────────────────────────────────────────────

/** Run ssh until it ends; resolves with what it said. `onUp` is called once it has stayed up long enough to count as connected. */
export function runSsh(args, { onUp, upAfterMs = 3000, spawnImpl = spawn } = {}) {
  return new Promise((resolve) => {
    const child = spawnImpl("ssh", args, { stdio: ["ignore", "ignore", "pipe"], windowsHide: true });
    let stderr = "";
    let up = false;
    const timer = setTimeout(() => { up = true; onUp?.(); }, upAfterMs);
    child.stderr?.on("data", (d) => { stderr = (stderr + d).slice(-4000); });
    child.once("error", (e) => { clearTimeout(timer); resolve({ code: -1, stderr: stderr || e.message, up, child }); });
    child.once("exit", (code) => { clearTimeout(timer); resolve({ code, stderr, up }); });
    runSsh.current = child;
  });
}

/**
 * Take ssh down with this program however this program ends: Ctrl+C, the terminal window closing, a normal exit. Without it an
 * ssh left behind would keep the tunnel (and the server's port) alive with nothing supervising it. (A hard kill of this process
 * cannot be caught; the next run finds the port held, and says so.)
 */
export function installCleanup(proc, stop, kill) {
  const once = (event) => proc.once(event, () => { stop(); kill(); });
  for (const e of ["SIGINT", "SIGTERM", "SIGHUP", "SIGBREAK"]) once(e);
  proc.once("exit", kill);
}

export async function superviseTunnel(conn, { sleep = (s) => new Promise((r) => setTimeout(r, s * 1000)), run = runSsh, stopped = () => false, now = () => Date.now() } = {}) {
  let failures = 0;
  let portHeld = 0;
  for (;;) {
    if (stopped()) return EXIT.OK;
    const started = now();
    const r = await run(sshArgs(conn), { onUp: () => { ok(`Connected. The server can now reach your app on port ${conn.appPort}. Leave this window open; press Ctrl+C to disconnect.`); } });
    if (stopped()) return EXIT.OK;
    const lasted = (now() - started) / 1000;
    const c = classifySsh(r.stderr);
    if (c.fatal) { bad(c.say); return c.exit; }
    if (lasted >= 30) { failures = 0; portHeld = 0; }
    if (c.kind === "port-held") {
      portHeld++;
      if (portHeld >= 8) { bad(c.say); return c.exit; }
      bad(`${c.say} (try ${portHeld} of 8)`);
      await sleep(c.wait);
      continue;
    }
    failures++;
    if (c.kind === "unknown" && failures >= 10) { bad(`Giving up after ${failures} failed tries. Last message: ${c.say}`); return EXIT.GAVE_UP; }
    const wait = backoff(failures - 1);
    bad(`${c.say} Retrying in ${wait}s.`);
    await sleep(wait);
  }
}

// ── main ────────────────────────────────────────────────────────────────────

export async function main(argv = process.argv.slice(2), env = process.env) {
  let opts;
  try {
    opts = parseArgs(argv, env);
  } catch (e) {
    if (!(e instanceof InputError)) throw e;
    console.error(`\n${e.message}\n\n${USAGE}`);
    return EXIT.INPUT;
  }
  if (opts.help) { say(USAGE); return EXIT.OK; }

  say("\nTentoroForge Watch live connector\n");
  const major = Number(process.versions.node.split(".")[0]);
  if (major < 18) { bad(`This needs Node 18 or newer (this is ${process.versions.node}).`); return EXIT.INPUT; }
  for (const tool of ["ssh", "ssh-keygen"]) {
    if (!findTool(tool)) { bad(`\`${tool}\` was not found on this computer. ${SSH_HELP}`); return EXIT.INPUT; }
  }

  say("1. Your app");
  const app = await localApp(opts.app);
  if (!app.ok) {
    bad(`Nothing is answering on port ${opts.app} on this computer.`);
    info(app.others.length ? `Something is running on port ${app.others.join(", ")}. Did you mean --app ${app.others[0]}?` : "Start your app first (for example: npm run dev), then run this again.");
    return EXIT.INPUT;
  }
  ok(`Your app is answering on port ${opts.app}.`);
  if (opts.keyFile && !looksLikeApp(opts.dir)) {
    bad(`${opts.dir} does not look like your app's folder (no package.json with a dev script).`);
    info("Run this from the app's folder, or pass --dir <the folder>. (--no-key-file skips this, but then you must copy the debug key yourself.)");
    return EXIT.INPUT;
  }

  say("2. The server");
  const host = new URL(opts.server).hostname;
  let addresses = [];
  try { addresses = (await dns.lookup(host, { all: true })).map((a) => a.address); } catch (e) { bad(`Cannot find ${host}: ${e.code || e.message}. Check the address and your internet connection.`); return EXIT.INPUT; }
  ok(`${host} is at ${addresses.join(", ")}.`);
  // Where to connect is public, so it is asked for and TESTED before the one-time code is spent: a blocked port costs nothing.
  let where;
  try {
    const r = await getJson(`${opts.server}/api/tunnel/info`);
    if (r.status !== 200) { bad(explainInfo(r.status, r.data)); return EXIT.INPUT; }
    where = r.data;
  } catch (e) {
    bad(e.message);
    info("Check that the address is the one you open in your browser, and that this computer can reach it.");
    return EXIT.INPUT;
  }
  const sshHost = opts.sshHost || where.sshHost;
  const sshPort = Number(opts.sshPort || where.sshPort);
  let ips = [];
  try { ips = (await dns.lookup(sshHost, { all: true })).map((a) => a.address); } catch { /* an IP address needs no lookup */ }
  const reach = await tcpCheck(sshHost, sshPort, 8000);
  if (!reach.ok) {
    bad(explainTcp(sshHost, sshPort, reach));
    info(`Your code has not been used. Ask whoever runs the server to open TCP port ${sshPort} to this computer's address, then run this again.`);
    return EXIT.INPUT;
  }
  ok(`Reached the tunnel at ${sshHost}${ips.length ? ` (${ips[0]})` : ""}:${sshPort} in ${reach.ms} ms.`);

  say("3. Pairing");
  sweepKeys();
  const fresh = newKey();
  const secret = newSecret();
  let res;
  try {
    res = await postJson(`${opts.server}/api/tunnel/pair`, { code: opts.code, publicKey: fresh.publicKey, appPort: opts.app, secret, label: opts.label });
  } catch (e) {
    sweepKeys();
    bad(e.message);
    info("Check that the address is the one you open in your browser, and that this computer can reach it.");
    return EXIT.INPUT;
  }
  if (res.status !== 200) { sweepKeys(); bad(explainPair(res.status, res.data)); return EXIT.INPUT; }
  const t = res.data;
  if (t.hostKey !== where.hostKey) {
    // The identity it was about to trust is not the one the server just gave: stop, and say so.
    sweepKeys();
    bad("The server's identity changed between two steps of the same run, so this connector stopped. Ask for a new code and try again.");
    return EXIT.SERVER_IDENTITY;
  }
  const keyFile = keepKey(fresh.keyFile, t.projectId);
  ok(`Paired${t.yourAddress ? `: the server sees this computer as ${t.yourAddress}` : ""}.`);

  fs.mkdirSync(HOME, { recursive: true, mode: 0o700 });
  const knownHostsFile = path.join(HOME, "known_hosts");
  fs.writeFileSync(knownHostsFile, knownHostsLine(sshHost, sshPort, t.hostKey) + "\n", { mode: 0o600 });

  if (opts.keyFile) {
    try {
      const file = writeSecret(opts.dir, secret);
      ok(`Wrote the app's debug key to ${file} (the running app picks it up by itself).`);
    } catch (e) {
      bad(`Could not write the debug key into ${opts.dir}: ${e.message}`);
      return EXIT.INPUT;
    }
  } else {
    info(`Debug key (put it in .forge-debug-secret in your app's folder): ${secret}`);
  }

  say("4. Tunnel");
  const conn = { user: t.sshUser, host: sshHost, port: sshPort, remotePort: t.port, appPort: opts.app, keyFile, knownHostsFile };
  let stop = false;
  installCleanup(process, () => { stop = true; }, () => { try { runSsh.current?.kill(); } catch { /* already gone */ } });
  // Say it if the app stops or starts answering while the tunnel is up: the tunnel itself needs no restart.
  let appUp = true;
  const watcher = setInterval(async () => {
    const now = (await tcpCheck("127.0.0.1", opts.app, 1500)).ok || (await tcpCheck("::1", opts.app, 1500)).ok;
    if (now !== appUp) { appUp = now; (now ? ok : bad)(now ? `Your app is answering on port ${opts.app} again.` : `Your app stopped answering on port ${opts.app}. The tunnel stays up; start the app again.`); }
  }, 20000);
  watcher.unref();
  const code = await superviseTunnel(conn, { stopped: () => stop });
  clearInterval(watcher);
  say(code === EXIT.OK ? "\nDisconnected." : `\nStopped (exit code ${code}).`);
  return code;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().then((code) => process.exit(code), (e) => { console.error(`\nUnexpected problem: ${e?.stack || e}`); process.exit(EXIT.GAVE_UP); });
}
