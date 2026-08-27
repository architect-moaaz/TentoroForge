/**
 * Runtime MCP client pool for generated apps.
 *
 *   callMcpTool(serverId, toolName, args) -> tool result
 *   listMcpToolsForServer(serverId)       -> [{name, description, inputSchema}]
 *
 * A singleton `Map<serverId, Client>` cache keyed by the platform-side
 * PlatformMcpServer row id. Clients are memoised across calls; a
 * disconnect-shaped failure evicts the cached client and retries the
 * call once.
 *
 * ── Package choice ─────────────────────────────────────────────────
 * We depend on `@modelcontextprotocol/sdk` (v1.x). The newer
 * `@modelcontextprotocol/client` (v2.x) exists but its zod peer bumps
 * to ^4.2 which conflicts with the rest of the standalone-app
 * template (still on zod ^3). The v1 SDK is the drop-in choice: same
 * `Client` + `StreamableHTTPClientTransport` + `SSEClientTransport`
 * exports, actively maintained, and its zod peer is `^3.25 || ^4.0`
 * so npm can resolve alongside the template's zod pin.
 *
 * ── Env contract (per server) ──────────────────────────────────────
 *   MCP_SERVER_{ID}_URL          required. absolute http/https URL.
 *   MCP_SERVER_{ID}_TRANSPORT    "http" | "sse"  (default: "http")
 *   MCP_SERVER_{ID}_AUTH_KIND    "none" | "bearer" | "apikey_header"
 *   MCP_SERVER_{ID}_SECRET       required when AUTH_KIND != "none"
 *   MCP_SERVER_{ID}_AUTH_HEADER  header name for "apikey_header"
 *
 * `{ID}` is the PlatformMcpServer row id normalised to uppercase hex
 * (first 12 chars of `uuid.hex`). The env is written by the platform's
 * runtime injector; the generated app never reads secrets directly.
 *
 * ── Runtime target ─────────────────────────────────────────────────
 * Pure Node module. No Next.js dependency. Works in Vercel serverless
 * (fresh Map per cold start — memoisation is per-instance) and in
 * long-lived Node servers (memoisation is stable for the process).
 */

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { SSEClientTransport } from "@modelcontextprotocol/sdk/client/sse.js";

// ── Errors ──────────────────────────────────────────────────────────

export type McpToolErrorKind =
  | "unreachable"
  | "auth"
  | "protocol"
  | "tool_error"
  | "missing_config";

export class McpToolError extends Error {
  readonly kind: McpToolErrorKind;
  readonly serverId: string;
  readonly cause?: unknown;

  constructor(
    kind: McpToolErrorKind,
    serverId: string,
    message: string,
    cause?: unknown,
  ) {
    super(`[mcp:${kind}] ${serverId}: ${message}`);
    this.name = "McpToolError";
    this.kind = kind;
    this.serverId = serverId;
    this.cause = cause;
  }
}

// ── Public API ──────────────────────────────────────────────────────

export interface McpToolContentPart {
  type: string;
  text?: string;
}

export interface McpToolCallResult {
  content: Array<McpToolContentPart>;
  isError: boolean;
}

export interface McpToolListEntry {
  name: string;
  description?: string;
  inputSchema?: unknown;
}

export async function callMcpTool(
  serverId: string,
  toolName: string,
  args: Record<string, unknown>,
): Promise<McpToolCallResult> {
  return withReconnectRetry(serverId, async (client) => {
    let raw: unknown;
    try {
      raw = await client.callTool({ name: toolName, arguments: args });
    } catch (err) {
      throw classifyCallError(serverId, err);
    }
    return normaliseCallResult(raw);
  });
}

export async function listMcpToolsForServer(
  serverId: string,
): Promise<Array<McpToolListEntry>> {
  return withReconnectRetry(serverId, async (client) => {
    let raw: unknown;
    try {
      raw = await client.listTools();
    } catch (err) {
      throw classifyCallError(serverId, err);
    }
    return normaliseToolList(raw);
  });
}

// ── Internal: connection pool ───────────────────────────────────────

interface PooledClient {
  client: Client;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  transport: any;
}

const pool: Map<string, PooledClient> = new Map();
const connecting: Map<string, Promise<PooledClient>> = new Map();

interface ServerConfig {
  url: string;
  transport: "http" | "sse";
  authKind: "none" | "bearer" | "apikey_header";
  secret?: string;
  authHeader?: string;
}

function readConfig(serverId: string): ServerConfig {
  const prefix = `MCP_SERVER_${serverId}_`;
  const url = process.env[`${prefix}URL`];
  if (!url) {
    throw new McpToolError(
      "missing_config",
      serverId,
      `env ${prefix}URL is not set`,
    );
  }
  const transportRaw = (process.env[`${prefix}TRANSPORT`] ?? "http").toLowerCase();
  if (transportRaw !== "http" && transportRaw !== "sse") {
    throw new McpToolError(
      "missing_config",
      serverId,
      `env ${prefix}TRANSPORT must be "http" or "sse" (got "${transportRaw}")`,
    );
  }
  const authKindRaw = (process.env[`${prefix}AUTH_KIND`] ?? "none").toLowerCase();
  if (
    authKindRaw !== "none" &&
    authKindRaw !== "bearer" &&
    authKindRaw !== "apikey_header"
  ) {
    throw new McpToolError(
      "missing_config",
      serverId,
      `env ${prefix}AUTH_KIND must be one of none|bearer|apikey_header`,
    );
  }
  const secret = process.env[`${prefix}SECRET`];
  const authHeader = process.env[`${prefix}AUTH_HEADER`];
  if (authKindRaw !== "none" && !secret) {
    throw new McpToolError(
      "missing_config",
      serverId,
      `env ${prefix}SECRET is required when AUTH_KIND=${authKindRaw}`,
    );
  }
  if (authKindRaw === "apikey_header" && !authHeader) {
    throw new McpToolError(
      "missing_config",
      serverId,
      `env ${prefix}AUTH_HEADER is required when AUTH_KIND=apikey_header`,
    );
  }
  return {
    url,
    transport: transportRaw,
    authKind: authKindRaw,
    secret,
    authHeader,
  };
}

function buildAuthHeaders(cfg: ServerConfig): Record<string, string> {
  if (cfg.authKind === "bearer" && cfg.secret) {
    return { Authorization: `Bearer ${cfg.secret}` };
  }
  if (cfg.authKind === "apikey_header" && cfg.secret && cfg.authHeader) {
    return { [cfg.authHeader]: cfg.secret };
  }
  return {};
}

async function getOrConnect(serverId: string): Promise<PooledClient> {
  const existing = pool.get(serverId);
  if (existing) return existing;

  const inFlight = connecting.get(serverId);
  if (inFlight) return inFlight;

  const promise = (async (): Promise<PooledClient> => {
    const cfg = readConfig(serverId);
    const headers = buildAuthHeaders(cfg);

    let transport: unknown;
    try {
      if (cfg.transport === "sse") {
        transport = new SSEClientTransport(new URL(cfg.url), {
          requestInit: { headers },
          eventSourceInit: {
            // Some MCP servers require the auth header on the SSE stream too.
            // The SDK accepts a custom fetch here for exactly that reason.
            fetch: (input, init) =>
              fetch(input as RequestInfo, { ...init, headers: { ...(init?.headers ?? {}), ...headers } }),
          },
        });
      } else {
        transport = new StreamableHTTPClientTransport(new URL(cfg.url), {
          requestInit: { headers },
        });
      }
    } catch (err) {
      throw new McpToolError(
        "protocol",
        serverId,
        `could not construct ${cfg.transport} transport`,
        err,
      );
    }

    const client = new Client(
      { name: "tentoro-forge-app", version: "1.0.0" },
      { capabilities: {} },
    );

    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      await client.connect(transport as any);
    } catch (err) {
      throw classifyConnectError(serverId, err);
    }

    const pooled: PooledClient = { client, transport };
    pool.set(serverId, pooled);

    // Drop the cached client on transport close so the next call reconnects.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const t = transport as any;
    const priorOnClose = t.onclose as (() => void) | undefined;
    t.onclose = () => {
      pool.delete(serverId);
      if (priorOnClose) {
        try {
          priorOnClose();
        } catch {
          /* swallow */
        }
      }
    };

    return pooled;
  })();

  connecting.set(serverId, promise);
  try {
    return await promise;
  } finally {
    connecting.delete(serverId);
  }
}

async function withReconnectRetry<T>(
  serverId: string,
  fn: (client: Client) => Promise<T>,
): Promise<T> {
  const pooled = await getOrConnect(serverId);
  try {
    return await fn(pooled.client);
  } catch (err) {
    if (err instanceof McpToolError && err.kind === "unreachable") {
      // Transport is dead — evict and try one more time with a fresh client.
      pool.delete(serverId);
      try {
        await pooled.client.close();
      } catch {
        /* swallow */
      }
      const fresh = await getOrConnect(serverId);
      return await fn(fresh.client);
    }
    throw err;
  }
}

// ── Internal: error classification + result shaping ────────────────

function classifyConnectError(serverId: string, err: unknown): McpToolError {
  const msg = err instanceof Error ? err.message : String(err);
  const lower = msg.toLowerCase();
  if (
    lower.includes("401") ||
    lower.includes("403") ||
    lower.includes("unauthor") ||
    lower.includes("forbidden")
  ) {
    return new McpToolError("auth", serverId, msg, err);
  }
  if (
    lower.includes("econnrefused") ||
    lower.includes("enotfound") ||
    lower.includes("timeout") ||
    lower.includes("fetch failed") ||
    lower.includes("network")
  ) {
    return new McpToolError("unreachable", serverId, msg, err);
  }
  return new McpToolError("protocol", serverId, msg, err);
}

function classifyCallError(serverId: string, err: unknown): McpToolError {
  if (err instanceof McpToolError) return err;
  const msg = err instanceof Error ? err.message : String(err);
  const lower = msg.toLowerCase();
  if (
    lower.includes("closed") ||
    lower.includes("disconnected") ||
    lower.includes("econnreset") ||
    lower.includes("socket") ||
    lower.includes("fetch failed") ||
    lower.includes("network")
  ) {
    return new McpToolError("unreachable", serverId, msg, err);
  }
  if (lower.includes("401") || lower.includes("403") || lower.includes("unauthor")) {
    return new McpToolError("auth", serverId, msg, err);
  }
  return new McpToolError("tool_error", serverId, msg, err);
}

function normaliseCallResult(raw: unknown): McpToolCallResult {
  if (!raw || typeof raw !== "object") {
    return { content: [], isError: false };
  }
  const r = raw as { content?: unknown; isError?: unknown };
  const content = Array.isArray(r.content)
    ? (r.content as Array<unknown>).map((p): McpToolContentPart => {
        if (p && typeof p === "object") {
          const part = p as { type?: unknown; text?: unknown };
          return {
            type: typeof part.type === "string" ? part.type : "text",
            text: typeof part.text === "string" ? part.text : undefined,
          };
        }
        return { type: "text", text: String(p) };
      })
    : [];
  return { content, isError: Boolean(r.isError) };
}

function normaliseToolList(raw: unknown): Array<McpToolListEntry> {
  if (!raw || typeof raw !== "object") return [];
  const r = raw as { tools?: unknown };
  if (!Array.isArray(r.tools)) return [];
  return (r.tools as Array<unknown>)
    .map((t): McpToolListEntry | null => {
      if (!t || typeof t !== "object") return null;
      const tool = t as {
        name?: unknown;
        description?: unknown;
        inputSchema?: unknown;
      };
      if (typeof tool.name !== "string") return null;
      return {
        name: tool.name,
        description:
          typeof tool.description === "string" ? tool.description : undefined,
        inputSchema: tool.inputSchema,
      };
    })
    .filter((x): x is McpToolListEntry => x !== null);
}

// ── Test hooks (not part of the public API) ─────────────────────────

/**
 * Evict every cached client. Intended for test tear-down; production
 * code should never need to call this.
 */
export function __resetMcpPool(): void {
  pool.clear();
  connecting.clear();
}
