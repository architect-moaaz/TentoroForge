/**
 * Vitest tests for mcpClientPool.
 *
 * The runtime template does not yet ship a vitest config (existing runtime
 * tests use `node --experimental-strip-types` on `.test.mts`, which cannot
 * mock ESM constructors from an external SDK). This file is authored in
 * the vitest style so it is drop-in ready once a test runner is wired
 * into the standalone-app template. Until then, treat it as executable
 * documentation of the pool's contract.
 *
 * Coverage:
 *   - getOrConnect reads the MCP_SERVER_{ID}_* env vars
 *   - callMcpTool unwraps content on success
 *   - McpToolError kind="missing_config" when env is absent
 *   - two consecutive calls for the same server reuse one Client
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// ── Mock the SDK before importing the module under test ──────────────

const callToolMock = vi.fn();
const listToolsMock = vi.fn();
const connectMock = vi.fn();
const closeMock = vi.fn();
const clientCtor = vi.fn();
const httpTransportCtor = vi.fn();
const sseTransportCtor = vi.fn();

vi.mock("@modelcontextprotocol/sdk/client/index.js", () => ({
  Client: vi.fn().mockImplementation((...args: unknown[]) => {
    clientCtor(...args);
    return {
      connect: connectMock,
      close: closeMock,
      callTool: callToolMock,
      listTools: listToolsMock,
    };
  }),
}));

vi.mock("@modelcontextprotocol/sdk/client/streamableHttp.js", () => ({
  StreamableHTTPClientTransport: vi
    .fn()
    .mockImplementation((url: URL, opts: unknown) => {
      httpTransportCtor(url, opts);
      return { onclose: undefined };
    }),
}));

vi.mock("@modelcontextprotocol/sdk/client/sse.js", () => ({
  SSEClientTransport: vi.fn().mockImplementation((url: URL, opts: unknown) => {
    sseTransportCtor(url, opts);
    return { onclose: undefined };
  }),
}));

// Late import so the mocks are hoisted.
import {
  callMcpTool,
  listMcpToolsForServer,
  McpToolError,
  __resetMcpPool,
} from "../mcpClientPool";

// ── Env helpers ──────────────────────────────────────────────────────

const ID = "AB12CD34EF56";
const PREFIX = `MCP_SERVER_${ID}_`;

function setEnv(overrides: Record<string, string | undefined>): void {
  for (const [k, v] of Object.entries(overrides)) {
    if (v === undefined) delete process.env[k];
    else process.env[k] = v;
  }
}

beforeEach(() => {
  __resetMcpPool();
  callToolMock.mockReset();
  listToolsMock.mockReset();
  connectMock.mockReset().mockResolvedValue(undefined);
  closeMock.mockReset().mockResolvedValue(undefined);
  clientCtor.mockReset();
  httpTransportCtor.mockReset();
  sseTransportCtor.mockReset();
  setEnv({
    [`${PREFIX}URL`]: "https://mcp.example.com/rpc",
    [`${PREFIX}TRANSPORT`]: "http",
    [`${PREFIX}AUTH_KIND`]: "bearer",
    [`${PREFIX}SECRET`]: "sk-test-abc",
    [`${PREFIX}AUTH_HEADER`]: undefined,
  });
});

afterEach(() => {
  setEnv({
    [`${PREFIX}URL`]: undefined,
    [`${PREFIX}TRANSPORT`]: undefined,
    [`${PREFIX}AUTH_KIND`]: undefined,
    [`${PREFIX}SECRET`]: undefined,
    [`${PREFIX}AUTH_HEADER`]: undefined,
  });
});

// ── Tests ────────────────────────────────────────────────────────────

describe("getOrConnect (via callMcpTool)", () => {
  it("reads env correctly and constructs an http transport with bearer auth", async () => {
    callToolMock.mockResolvedValue({
      content: [{ type: "text", text: "hi" }],
      isError: false,
    });

    await callMcpTool(ID, "search", { q: "socks" });

    expect(httpTransportCtor).toHaveBeenCalledTimes(1);
    const [url, opts] = httpTransportCtor.mock.calls[0] as [URL, { requestInit?: { headers?: Record<string, string> } }];
    expect(url.toString()).toBe("https://mcp.example.com/rpc");
    expect(opts?.requestInit?.headers?.Authorization).toBe("Bearer sk-test-abc");
    expect(connectMock).toHaveBeenCalledTimes(1);
    expect(sseTransportCtor).not.toHaveBeenCalled();
  });

  it("uses SSEClientTransport when TRANSPORT=sse", async () => {
    setEnv({ [`${PREFIX}TRANSPORT`]: "sse" });
    callToolMock.mockResolvedValue({ content: [], isError: false });

    await callMcpTool(ID, "search", {});

    expect(sseTransportCtor).toHaveBeenCalledTimes(1);
    expect(httpTransportCtor).not.toHaveBeenCalled();
  });
});

describe("callMcpTool", () => {
  it("returns unwrapped content on success", async () => {
    callToolMock.mockResolvedValue({
      content: [{ type: "text", text: "result body" }],
      isError: false,
    });

    const out = await callMcpTool(ID, "search", { q: "socks" });

    expect(out).toEqual({
      content: [{ type: "text", text: "result body" }],
      isError: false,
    });
    expect(callToolMock).toHaveBeenCalledWith({
      name: "search",
      arguments: { q: "socks" },
    });
  });

  it("throws McpToolError kind='missing_config' when URL env is absent", async () => {
    setEnv({ [`${PREFIX}URL`]: undefined });

    await expect(callMcpTool(ID, "search", {})).rejects.toMatchObject({
      name: "McpToolError",
      kind: "missing_config",
      serverId: ID,
    });
    expect(connectMock).not.toHaveBeenCalled();
  });

  it("throws McpToolError kind='missing_config' when bearer secret missing", async () => {
    setEnv({ [`${PREFIX}SECRET`]: undefined });

    const err = await callMcpTool(ID, "search", {}).catch((e) => e);
    expect(err).toBeInstanceOf(McpToolError);
    expect((err as McpToolError).kind).toBe("missing_config");
  });
});

describe("memoisation", () => {
  it("two consecutive calls for the same server reuse one Client", async () => {
    callToolMock.mockResolvedValue({ content: [], isError: false });

    await callMcpTool(ID, "search", {});
    await callMcpTool(ID, "search", { q: "again" });

    expect(clientCtor).toHaveBeenCalledTimes(1);
    expect(connectMock).toHaveBeenCalledTimes(1);
    expect(httpTransportCtor).toHaveBeenCalledTimes(1);
    expect(callToolMock).toHaveBeenCalledTimes(2);
  });

  it("evicts + reconnects after an unreachable-shaped call failure", async () => {
    callToolMock
      .mockRejectedValueOnce(new Error("socket hang up"))
      .mockResolvedValueOnce({ content: [], isError: false });

    await callMcpTool(ID, "search", {});

    // First transport + client were built, evicted, then a second pair built.
    expect(clientCtor).toHaveBeenCalledTimes(2);
    expect(connectMock).toHaveBeenCalledTimes(2);
    expect(callToolMock).toHaveBeenCalledTimes(2);
  });
});

describe("listMcpToolsForServer", () => {
  it("returns the tools array with name/description/inputSchema", async () => {
    listToolsMock.mockResolvedValue({
      tools: [
        {
          name: "search",
          description: "Web search",
          inputSchema: { type: "object" },
        },
        { name: "crawl" },
      ],
    });

    const out = await listMcpToolsForServer(ID);

    expect(out).toEqual([
      {
        name: "search",
        description: "Web search",
        inputSchema: { type: "object" },
      },
      { name: "crawl", description: undefined, inputSchema: undefined },
    ]);
  });
});
