/**
 * Connecting the computer where the app runs (lib/watch-tunnel.ts): what is shown about the tunnel, the commands to paste,
 * and how a code counts down. Pinned: the platform's answer is taken as it is, whatever shape it comes in (a missing field is
 * never a crash); the commands carry the right address, code and port and no other way in; a port is a real port; and each
 * state of the tunnel is one plain sentence.
 */
import { describe, it, expect } from "vitest";
import { NO_TUNNEL, asTunnelState, clock, connectorCommands, secondsLeft, summarise, validPort } from "./watch-tunnel";

describe("what the platform says about the tunnel", () => {
  it("is read field by field, and anything odd is treated as not connected", () => {
    expect(asTunnelState({ enabled: true, registered: true, connected: true, port: 22001, appPort: 3001, clientIp: "1.2.3.4", label: "Ana laptop", pairedAt: 5 }))
      .toMatchObject({ enabled: true, registered: true, connected: true, port: 22001, appPort: 3001, clientIp: "1.2.3.4", label: "Ana laptop" });
    for (const odd of [null, undefined, "x", 5, [], {}, { enabled: "yes", connected: 1, port: "22001", appPort: NaN, clientIp: 7 }]) {
      expect(asTunnelState(odd), JSON.stringify(odd)).toMatchObject({ enabled: false, registered: false, connected: false, clientIp: null, appPort: null });
    }
    expect(NO_TUNNEL).toEqual({ enabled: false, registered: false, connected: false });
  });

  it("keeps where it is hosted when the platform says", () => {
    expect(asTunnelState({ enabled: true, hosted: { vercel: { url: "https://x.vercel.app" } } }).hosted?.vercel?.url).toBe("https://x.vercel.app");
    expect(asTunnelState({ enabled: true, hosted: "x" }).hosted).toBeUndefined();
  });
});

describe("the command to paste", () => {
  it("carries the server's address, the code and the port, for a shell and for PowerShell", () => {
    const c = connectorCommands("https://forge.example.com/", "ABCD-EFGH", 3001);
    expect(c.unix).toBe("curl -fsSL https://forge.example.com/api/tunnel/connector.mjs -o ttf-watch-connect.mjs && node ttf-watch-connect.mjs --server https://forge.example.com --code ABCD-EFGH --app 3001");
    expect(c.windows).toBe("Invoke-WebRequest https://forge.example.com/api/tunnel/connector.mjs -OutFile ttf-watch-connect.mjs; node ttf-watch-connect.mjs --server https://forge.example.com --code ABCD-EFGH --app 3001");
    expect(connectorCommands("http://localhost:3100", "WXYZ-2345", 3000).unix).toContain("--server http://localhost:3100 --code WXYZ-2345 --app 3000");
  });
});

describe("a port as typed", () => {
  it("is a whole number from 1 to 65535 and nothing else", () => {
    expect(validPort("3000")).toBe(3000);
    expect(validPort(" 65535 ")).toBe(65535);
    expect(validPort("1")).toBe(1);
    for (const bad of ["", "0", "65536", "abc", "30 00", "3000.5", "-1", "1e3", "http://localhost:3000", "123456"]) expect(validPort(bad), bad).toBeNull();
  });
});

describe("a code counting down", () => {
  it("shows minutes and seconds and never goes below zero", () => {
    const p = { code: "ABCD-EFGH", expiresAt: 1000 };
    expect(secondsLeft(p, 400_000)).toBe(600);
    expect(secondsLeft(p, 999_500), "half a second left still reads 1: never 0:00 while it works").toBe(1);
    expect(secondsLeft(p, 1_000_000)).toBe(0);
    expect(secondsLeft(p, 5_000_000)).toBe(0);
    expect([clock(600), clock(65), clock(5), clock(0), clock(-3)]).toEqual(["10:00", "1:05", "0:05", "0:00", "0:00"]);
  });
});

describe("the tunnel in a sentence", () => {
  it("says nothing is connected yet, when none is", () => {
    expect(summarise(NO_TUNNEL)).toEqual({ tone: "idle", text: "No computer connected yet." });
  });

  it("says who is connected, from where, and which port the app is on", () => {
    const s = summarise({ enabled: true, registered: true, connected: true, appPort: 3001, clientIp: "1.2.3.4", label: "Ana laptop" });
    expect(s).toEqual({ tone: "good", text: "Connected: Ana laptop (1.2.3.4), app on port 3001." });
    expect(summarise({ enabled: true, registered: true, connected: true, clientIp: "1.2.3.4" }).text).toBe("Connected: 1.2.3.4.");
    expect(summarise({ enabled: true, registered: true, connected: true }).text).toBe("Connected: your computer.");
  });

  it("says a paired computer that is not connected right now must run the connector again, and that it reconnects by itself", () => {
    const s = summarise({ enabled: true, registered: true, connected: false, label: "Ana laptop", clientIp: "1.2.3.4" });
    expect(s.tone).toBe("warn");
    expect(s.text).toContain("Ana laptop (1.2.3.4) is paired but not connected right now");
    expect(s.text).toContain("reconnects by itself");
  });
});
