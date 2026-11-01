// Tests for the Watch live connector. Run: node --test templates/tunnel/
// What is pinned: what is accepted and refused on the command line; what each way ssh can stop means and what the connector does
// about it (retry, wait, or stop and say why); the exact ssh command (quoting for paths with spaces, the one port, the pinned
// host key); the key it makes is a bare ed25519 key the server accepts; the debug key file; the retry rhythm and its limits.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import {
  EXIT, InputError, backoff, classifySsh, explainInfo, explainPair, explainTcp, findTool, getJson, installCleanup, keepKey, knownHostsLine, localApp, looksLikeApp, main, newKey,
  newSecret, parseArgs, postJson, sshArgs, sshOpt, superviseTunnel, sweepKeys, tcpCheck, writeSecret,
} from "./ttf-watch-connect.mjs";

const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), "ttf-connector-"));
const good = ["--server", "https://forge.example.com/some/page", "--code", "abcd-efgh", "--app", "3001"];

// ── the command line ───────────────────────────────────────────────────────

test("a good command line is understood, however the code is typed", () => {
  const o = parseArgs(good);
  assert.equal(o.server, "https://forge.example.com");
  assert.equal(o.code, "ABCDEFGH");
  assert.equal(o.app, 3001);
  assert.equal(o.keyFile, true);
  assert.equal(path.resolve(o.dir), path.resolve(process.cwd()));
  assert.equal(parseArgs(["--server", "http://localhost:3100", "--code", "ab cd 23-45", "--app", "3000"]).code, "ABCD2345");
});

test("everything may come from the environment instead", () => {
  const o = parseArgs([], { TTF_SERVER: "http://localhost:3100", TTF_CODE: "ABCD-EFGH", TTF_APP_PORT: "3002" });
  assert.deepEqual([o.server, o.code, o.app], ["http://localhost:3100", "ABCDEFGH", 3002]);
});

test("each wrong input says what is wrong", () => {
  const bad = (argv, re) => assert.throws(() => parseArgs(argv, {}), (e) => e instanceof InputError && re.test(e.message), argv.join(" "));
  bad([], /--server must be the TentoroForge address/);
  bad(["--server", "forge.example.com", "--code", "ABCDEFGH", "--app", "3000"], /--server must be/);
  bad(["--server", "ftp://x.com", "--code", "ABCDEFGH", "--app", "3000"], /--server must be/);
  bad(["--server", "https://x.com", "--code", "ABC", "--app", "3000"], /8-character code/);
  bad(["--server", "https://x.com", "--code", "ABCDEFGH"], /--app must be the port/);
  bad(["--server", "https://x.com", "--code", "ABCDEFGH", "--app", "0"], /--app must be the port/);
  bad(["--server", "https://x.com", "--code", "ABCDEFGH", "--app", "99999"], /--app must be the port/);
  bad(["--server", "https://x.com", "--code", "ABCDEFGH", "--app", "http://localhost:3000"], /--app must be the port/);
  bad([...good, "--wat"], /I do not know "--wat"/);
  bad(["--server"], /--server needs a value/);
  bad(["--server", "--code"], /--server needs a value/);
  bad([...good, "--ssh-port", "abc"], /--ssh-port/);
});

test("--help needs nothing else, and a label is made safe", () => {
  assert.equal(parseArgs(["--help"]).help, true);
  assert.equal(parseArgs(["-h"]).help, true);
  assert.equal(parseArgs([...good, "--label", "Ana's <laptop>; rm -rf"]).label, "Anas laptop rm -rf");
  assert.ok(parseArgs(good).label.length > 0);
});

// ── what ssh says when it stops ────────────────────────────────────────────

test("every way ssh can stop is sorted into stop, wait, or retry", () => {
  const key = classifySsh("tunnel@1.2.3.4: Permission denied (publickey).");
  assert.deepEqual([key.kind, key.fatal, key.exit], ["key-removed", true, EXIT.KEY_REMOVED]);
  assert.match(key.say, /Ask for a new code/);
  assert.equal(classifySsh("Too many authentication failures").kind, "key-removed");

  for (const t of ["Host key verification failed.", "@@@ WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED! @@@"]) {
    const id = classifySsh(t);
    assert.deepEqual([id.kind, id.fatal, id.exit], ["identity", true, EXIT.SERVER_IDENTITY]);
  }

  for (const t of ["Error: remote port forwarding failed for listen port 22001", "bind: Address already in use"]) {
    const held = classifySsh(t);
    assert.deepEqual([held.kind, held.fatal, held.wait], ["port-held", false, 15]);
    assert.match(held.say, /45 seconds/);
  }

  for (const t of ["ssh: connect to host x port 2222: Connection timed out", "Connection reset by peer", "ssh: connect to host x port 2222: Network is unreachable",
    "kex_exchange_identification: read: Connection reset by peer", "Connection closed by 1.2.3.4 port 2222", "Broken pipe", "ssh: connect to host x port 2222: Connection refused",
    "ssh: connect to host x port 2222: No route to host"]) {
    const n = classifySsh(t);
    assert.deepEqual([n.kind, n.fatal], ["network", false], t);
  }
  assert.match(classifySsh("ssh: Could not resolve hostname nope: Name or service not known").say, /internet connection and DNS/);

  const odd = classifySsh("something\nentirely\nunexpected here");
  assert.deepEqual([odd.kind, odd.fatal], ["unknown", false]);
  assert.match(odd.say, /entirely unexpected here/);
  assert.equal(classifySsh("").say, "ssh stopped.");
});

test("the wait before a retry grows and then stops growing", () => {
  assert.deepEqual([0, 1, 2, 3, 4, 5, 20].map(backoff), [2, 4, 8, 16, 30, 30, 30]);
});

// ── the ssh command ────────────────────────────────────────────────────────

test("a path with spaces is quoted for ssh, and backslashes become slashes", () => {
  assert.equal(sshOpt("UserKnownHostsFile", "C:\\Users\\Ana Smith\\.ttf-watch\\known_hosts"), 'UserKnownHostsFile="C:/Users/Ana Smith/.ttf-watch/known_hosts"');
  assert.equal(sshOpt("UserKnownHostsFile", "/home/ana/.ttf-watch/known_hosts"), "UserKnownHostsFile=/home/ana/.ttf-watch/known_hosts");
});

test("the host key line names the port unless it is 22", () => {
  assert.equal(knownHostsLine("13.212.213.53", 2222, "ssh-ed25519 AAAA"), "[13.212.213.53]:2222 ssh-ed25519 AAAA");
  assert.equal(knownHostsLine("example.com", 22, "ssh-ed25519 AAAA"), "example.com ssh-ed25519 AAAA");
});

test("the ssh command forwards one port, trusts only the pinned key, never asks a question, and notices a dead connection", () => {
  const a = sshArgs({ user: "tunnel", host: "h", port: 2222, remotePort: 22001, appPort: 3001, keyFile: "/k/id", knownHostsFile: "/k/kh" });
  const at = (opt) => a[a.indexOf(opt) + 1];
  assert.equal(at("-R"), "0.0.0.0:22001:localhost:3001");
  assert.equal(at("-p"), "2222");
  assert.equal(at("-i"), "/k/id");
  assert.equal(a.at(-1), "tunnel@h");
  const opts = a.filter((_, i) => a[i - 1] === "-o");
  for (const want of ["StrictHostKeyChecking=yes", "BatchMode=yes", "IdentitiesOnly=yes", "PasswordAuthentication=no", "ExitOnForwardFailure=yes", "ServerAliveInterval=15", "ServerAliveCountMax=3", "ConnectTimeout=10", "UserKnownHostsFile=/k/kh"]) {
    assert.ok(opts.includes(want), want);
  }
  assert.ok(a.includes("-N") && a.includes("-T"), "no shell, no terminal");
  assert.equal(a.filter((x) => x === "-R").length, 1, "one forward and no more");
});

// ── looking at the network and at this computer ────────────────────────────

const listen = () => new Promise((resolve) => { const s = net.createServer((c) => c.end()); s.listen(0, "127.0.0.1", () => resolve(s)); });

test("a port that answers is reachable and one that does not says why", async () => {
  const s = await listen();
  const port = s.address().port;
  try {
    const up = await tcpCheck("127.0.0.1", port, 2000);
    assert.equal(up.ok, true);
    assert.equal(explainTcp("h", port, up), "");
  } finally { s.close(); }
  const down = await tcpCheck("127.0.0.1", port, 2000);
  assert.deepEqual([down.ok, down.why], [false, "ECONNREFUSED"]);
  assert.match(explainTcp("h", 2222, down), /Nothing is listening on h:2222/);
  assert.match(explainTcp("h", 2222, { ok: false, why: "timeout" }), /firewall.*blocking port 2222/);
  assert.match(explainTcp("h", 2222, { ok: false, why: "ENOTFOUND" }), /Cannot find h/);
  assert.match(explainTcp("h", 2222, { ok: false, why: "EHOSTUNREACH" }), /No route to h/);
  assert.match(explainTcp("h", 2222, { ok: false, why: "EWHAT" }), /\(EWHAT\)/);
});

test("the app on this computer is found, or its absence is reported", async () => {
  const s = await listen();
  const port = s.address().port;
  try {
    assert.equal((await localApp(port)).ok, true);
  } finally { s.close(); }
  const gone = await localApp(port);
  assert.equal(gone.ok, false);
  assert.ok(Array.isArray(gone.others));
});

test("the OpenSSH tools are looked for by name", () => {
  assert.equal(findTool("ssh"), true);
  assert.equal(findTool("definitely-not-a-real-program-xyz"), false);
});

// ── keys and files ─────────────────────────────────────────────────────────

test("each pairing makes a fresh bare ed25519 key the server accepts, filed under its project", { skip: !findTool("ssh-keygen") }, () => {
  const home = path.join(tmp(), "home");
  const a = newKey(home);
  assert.match(a.publicKey, /^ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI[A-Za-z0-9+/]{43}$/, "the same shape the platform insists on: no comment");
  const b = newKey(home);
  assert.notEqual(b.publicKey, a.publicKey, "a key belongs to one project, so there is a new one every time");

  const kept = keepKey(a.keyFile, "11111111-2222-3333-4444-555555555555", home);
  assert.equal(path.basename(kept), "project-11111111-2222-3333-4444-555555555555");
  assert.ok(fs.existsSync(kept) && fs.existsSync(`${kept}.pub`) && !fs.existsSync(a.keyFile), "moved, not copied");
  const again = keepKey(b.keyFile, "11111111-2222-3333-4444-555555555555", home);
  assert.equal(again, kept);
  assert.equal(fs.readFileSync(`${kept}.pub`, "utf8").split(/\s+/)[1], b.publicKey.split(" ")[1], "a new pairing for the same project replaces its key");
  assert.equal(keepKey(newKey(home).keyFile, "../../evil", home).includes(".."), false, "a project name cannot walk out of the folder");
});

test("keys from pairings that never finished are swept away, and the ones kept stay", { skip: !findTool("ssh-keygen") }, () => {
  const home = path.join(tmp(), "home");
  const kept = keepKey(newKey(home).keyFile, "aaaaaaaa-bbbb", home);
  const stray = newKey(home);
  sweepKeys(home);
  assert.equal(fs.existsSync(stray.keyFile), false);
  assert.equal(fs.existsSync(kept), true);
  sweepKeys(path.join(tmp(), "never-made"));
});

test("a secret is long enough and different each time", () => {
  const a = newSecret();
  assert.match(a, /^[A-Za-z0-9_-]{43}$/);
  assert.notEqual(a, newSecret());
});

test("an app folder is recognised by package.json, and the debug key is written and kept out of git", () => {
  const dir = tmp();
  assert.equal(looksLikeApp(dir), false);
  fs.writeFileSync(path.join(dir, "package.json"), "{ not json");
  assert.equal(looksLikeApp(dir), false);
  fs.writeFileSync(path.join(dir, "package.json"), JSON.stringify({ dependencies: { next: "15" } }));
  assert.equal(looksLikeApp(dir), true);

  const file = writeSecret(dir, "s".repeat(43));
  assert.equal(fs.readFileSync(file, "utf8"), "s".repeat(43) + "\n");
  assert.equal(fs.readFileSync(path.join(dir, ".gitignore"), "utf8"), ".forge-debug-secret\n");
  writeSecret(dir, "t".repeat(43));
  assert.equal(fs.readFileSync(file, "utf8"), "t".repeat(43) + "\n", "a new pairing replaces the key");
  assert.equal(fs.readFileSync(path.join(dir, ".gitignore"), "utf8"), ".forge-debug-secret\n", "and the ignore line is not repeated");
  fs.writeFileSync(path.join(dir, ".gitignore"), "node_modules\n.env");
  writeSecret(dir, "u".repeat(43));
  assert.equal(fs.readFileSync(path.join(dir, ".gitignore"), "utf8"), "node_modules\n.env\n.forge-debug-secret\n");
});

// ── talking to TentoroForge ────────────────────────────────────────────────

test("a network hiccup is retried and an answer is returned whatever its status", async () => {
  let calls = 0;
  const fetchImpl = async () => { calls++; if (calls < 3) throw new TypeError("fetch failed"); return { status: 404, json: async () => ({ detail: "nope" }) }; };
  const r = await postJson("http://x/api", { a: 1 }, { fetchImpl, tries: 3, timeoutMs: 1000 });
  assert.deepEqual([r.status, r.data, calls], [404, { detail: "nope" }, 3]);
});

test("a server that never answers is reported once, in words", async () => {
  const fetchImpl = async () => { throw Object.assign(new TypeError("fetch failed"), { cause: { code: "ECONNREFUSED" } }); };
  await assert.rejects(postJson("http://x/api", {}, { fetchImpl, tries: 2, timeoutMs: 500 }), (e) => e.network === true && /Could not reach http:\/\/x\/api: ECONNREFUSED/.test(e.message));
  const hang = (_u, { signal }) => new Promise((_r, rej) => signal.addEventListener("abort", () => rej(Object.assign(new Error("a"), { name: "AbortError" }))));
  await assert.rejects(postJson("http://x/api", {}, { fetchImpl: hang, tries: 1, timeoutMs: 20 }), /no answer in time/);
});

test("asking where to connect is a plain GET, retried like the rest", async () => {
  let seen;
  const fetchImpl = async (url, init) => { seen = [url, init.method, init.body]; return { status: 200, json: async () => ({ sshHost: "h" }) }; };
  const r = await getJson("http://x/api/tunnel/info", { fetchImpl });
  assert.deepEqual([r.status, r.data.sshHost, seen[1], seen[2]], [200, "h", "GET", undefined], "no body on a GET");
});

test("each answer to 'where do I connect' is explained", () => {
  assert.match(explainInfo(404, {}), /not a TentoroForge that supports Watch live/);
  assert.match(explainInfo(503, {}), /not ready/);
  assert.equal(explainInfo(503, { detail: "No public address." }), "No public address.");
  assert.match(explainInfo(500, {}), /HTTP 500/);
});

test("each refusal of a pairing is explained", () => {
  assert.match(explainPair(404, {}), /not valid, or it has expired/);
  assert.equal(explainPair(404, { detail: "That code is not valid, or it has expired. Ask for a new one in Watch live." }), "That code is not valid, or it has expired. Ask for a new one in Watch live.");
  assert.match(explainPair(429, {}), /Wait a minute/);
  assert.match(explainPair(409, {}), /already connected to another project/);
  assert.match(explainPair(503, {}), /not ready/);
  assert.equal(explainPair(503, { detail: "The platform does not know its address." }), "The platform does not know its address.");
  assert.match(explainPair(500, {}), /HTTP 500/);
});

// ── keeping the tunnel up ──────────────────────────────────────────────────

const conn = { user: "tunnel", host: "h", port: 2222, remotePort: 22001, appPort: 3001, keyFile: "k", knownHostsFile: "kh" };

function scripted(...results) {
  const sleeps = [];
  const calls = [];
  const run = async (args, opts) => { calls.push(args); const r = results.shift() ?? { stderr: "Permission denied (publickey)." }; if (r.up) opts.onUp(); return r; };
  return { run, sleeps, calls, sleep: async (s) => { sleeps.push(s); } };
}

test("a dropped network is retried with a growing wait, for as long as it takes, and the tunnel comes back", async () => {
  const net = { stderr: "ssh: connect to host h port 2222: Connection timed out" };
  const t = scripted(net, net, net, net, net, net, { stderr: "Permission denied (publickey)." });
  const code = await superviseTunnel(conn, { run: t.run, sleep: t.sleep });
  assert.equal(code, EXIT.KEY_REMOVED);
  assert.deepEqual(t.sleeps, [2, 4, 8, 16, 30, 30]);
  assert.equal(t.calls.length, 7, "it kept trying until something that cannot be fixed by waiting");
});

test("a key that was removed or a server that changed stops it at once, with a code that says which", async () => {
  assert.equal(await superviseTunnel(conn, { ...scripted({ stderr: "Permission denied (publickey)." }) }), EXIT.KEY_REMOVED);
  assert.equal(await superviseTunnel(conn, { ...scripted({ stderr: "Host key verification failed." }) }), EXIT.SERVER_IDENTITY);
});

test("a port held by another connection is waited out and, if it stays held, reported", async () => {
  const held = { stderr: "Error: remote port forwarding failed for listen port 22001" };
  const t = scripted(held, held, { stderr: "x", up: true }, held, held, held, held, held, held, held, held);
  // two tries, then a session that connected (but did not last 30 s), then it stays held: 8 consecutive tries ends it
  const code = await superviseTunnel(conn, { run: t.run, sleep: t.sleep });
  assert.equal(code, EXIT.PORT_HELD);
  assert.ok(t.sleeps.filter((s) => s === 15).length >= 7);
});

test("a long good session resets the counters, so a later drop starts the waits from the beginning", async () => {
  let clock = 0;
  const run = (() => {
    const steps = [
      async () => { clock += 5 * 1000; return { stderr: "Connection reset by peer" }; },
      async () => { clock += 5 * 1000; return { stderr: "Connection reset by peer" }; },
      async () => { clock += 600 * 1000; return { stderr: "Connection reset by peer" }; },
      async () => { clock += 1000; return { stderr: "Connection reset by peer" }; },
      async () => ({ stderr: "Permission denied (publickey)." }),
    ];
    return async () => steps.shift()();
  })();
  const sleeps = [];
  await superviseTunnel(conn, { run, sleep: async (s) => { sleeps.push(s); }, now: () => clock });
  assert.deepEqual(sleeps, [2, 4, 2, 4], "after the ten-minute session the waits start again from 2");
});

test("an unknown failure is retried a few times and then given up on, with ssh's own words", async () => {
  const odd = { stderr: "the sky fell" };
  const t = scripted(...Array(12).fill(odd));
  const code = await superviseTunnel(conn, { run: t.run, sleep: t.sleep });
  assert.equal(code, EXIT.GAVE_UP);
  assert.equal(t.calls.length, 10);
});

test("pressing Ctrl+C ends it cleanly, even while it waits to retry", async () => {
  let stop = false;
  const run = async () => { stop = true; return { stderr: "Connection reset by peer" }; };
  assert.equal(await superviseTunnel(conn, { run, sleep: async () => {}, stopped: () => stop }), EXIT.OK);
  assert.equal(await superviseTunnel(conn, { run: async () => ({ stderr: "" }), stopped: () => true }), EXIT.OK);
});

test("ssh goes down with the connector however the connector ends", async () => {
  const { EventEmitter } = await import("node:events");
  for (const how of ["SIGINT", "SIGTERM", "SIGHUP", "SIGBREAK", "exit"]) {
    const proc = new EventEmitter();
    const log = [];
    installCleanup(proc, () => log.push("stop"), () => log.push("kill"));
    proc.emit(how);
    assert.deepEqual(log, how === "exit" ? ["kill"] : ["stop", "kill"], how);
  }
});

// ── the whole program, as far as it can go without a server ─────────────────

test("it checks the app BEFORE anything else, and says what to do when nothing is running", { skip: !findTool("ssh") }, async () => {
  const s = await listen();
  const port = s.address().port;
  s.close();
  const lines = [];
  const orig = console.log;
  console.log = (...a) => lines.push(a.join(" "));
  try {
    const code = await main(["--server", "http://localhost:1", "--code", "ABCD-EFGH", "--app", String(port), "--dir", tmp()], {});
    assert.equal(code, EXIT.INPUT);
  } finally { console.log = orig; }
  const said = lines.join("\n");
  assert.match(said, new RegExp(`Nothing is answering on port ${port}`));
  assert.match(said, /Start your app first/);
  assert.doesNotMatch(said, /2\. The server/, "it never got as far as the server");
});

test("a folder that is not the app's is refused before the server is touched, with the way out", { skip: !findTool("ssh") }, async () => {
  const s = await listen();
  const lines = [];
  const orig = console.log;
  console.log = (...a) => lines.push(a.join(" "));
  try {
    const code = await main(["--server", "http://localhost:1", "--code", "ABCD-EFGH", "--app", String(s.address().port), "--dir", tmp()], {});
    assert.equal(code, EXIT.INPUT);
  } finally { console.log = orig; s.close(); }
  const said = lines.join("\n");
  assert.match(said, /does not look like your app's folder/);
  assert.match(said, /--no-key-file/);
  assert.doesNotMatch(said, /2\. The server/);
});
