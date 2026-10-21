/**
 * The application as an MCP server — the protocol, with nothing of Next.js in it.
 *
 * An assistant (Claude, or any MCP client) runs this app's processes and
 * reads its records the way a person does. The tools are written from the
 * definition into `catalog.json`; WHO may use each is decided where it always
 * is — the workflow route's launch gate and the data route's access table —
 * because a tool here calls those routes as the person whose token it holds.
 * This file only speaks the protocol: JSON-RPC 2.0 over one POST, answered
 * with one JSON reply (the "streamable HTTP" transport, without a stream).
 *
 * Platform file: every app carries it and the platform replaces it.
 */

export type CatalogWorkflow = {
  tool: string; id: string; name: string; description: string;
  roles: string[] | null; inputSchema: Record<string, unknown>;
};
export type CatalogRecord = {
  slug: string; name: string; description: string; find: string; get: string;
  fields: { name: string; type: string }[]; roles: string[] | null;
};
export type Catalog = { app: string; about?: string; workflows: CatalogWorkflow[]; records: CatalogRecord[] };

export type Person = { id: string; role?: string | null; email?: string | null; name?: string | null };

/** How a tool reaches the app: the same two routes a screen uses. */
export type Doors = {
  run: (workflowId: string, input: Record<string, unknown>) => Promise<{ status: number; body: unknown }>;
  read: (slug: string, id: string | null, query: Record<string, string>) => Promise<{ status: number; body: unknown }>;
};

type Rpc = { jsonrpc?: string; id?: string | number | null; method?: string; params?: any };

export const PROTOCOL_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"];

/** A gate as the routes read it: null is open to anyone signed in. */
function admits(roles: string[] | null | undefined, person: Person): boolean {
  if (!roles) return true;
  return roles.includes("*") || roles.includes("@signed-in") || roles.includes(String(person.role ?? ""));
}

export function toolsFor(catalog: Catalog, person: Person) {
  const tools: Array<Record<string, unknown>> = [];
  for (const w of catalog.workflows) {
    if (!admits(w.roles, person)) continue;
    tools.push({ name: w.tool, title: w.name, description: w.description || w.name, inputSchema: w.inputSchema,
                 annotations: { readOnlyHint: false } });
  }
  for (const r of catalog.records) {
    if (!admits(r.roles, person)) continue;
    const fields = r.fields.map((f) => f.name);
    tools.push({
      name: r.find, title: `Find ${r.name} records`,
      description: `Find ${r.name} records you can see${r.description ? ` — ${r.description}` : ""}. Fields: ${fields.join(", ")}.`,
      inputSchema: { type: "object", properties: {
        search: { type: "string", description: "Words to look for" },
        filters: { type: "object", description: `Field = value, any of: ${fields.join(", ")}`, additionalProperties: { type: "string" } },
        sort: { type: "string", enum: fields }, order: { type: "string", enum: ["asc", "desc"] },
        page: { type: "integer", minimum: 1 }, limit: { type: "integer", minimum: 1, maximum: 100 },
      } },
      annotations: { readOnlyHint: true },
    });
    tools.push({
      name: r.get, title: `Get one ${r.name} record`, description: `One ${r.name} record by its id.`,
      inputSchema: { type: "object", properties: { id: { type: "string" } }, required: ["id"] },
      annotations: { readOnlyHint: true },
    });
  }
  return tools;
}

const ok = (id: Rpc["id"], result: unknown) => ({ jsonrpc: "2.0", id: id ?? null, result });
const fail = (id: Rpc["id"], code: number, message: string) => ({ jsonrpc: "2.0", id: id ?? null, error: { code, message } });

function said(body: unknown): string {
  if (typeof body === "string") return body;
  try { return JSON.stringify(body, null, 2); } catch { return String(body); }
}

function refusal(status: number, body: any): string {
  const message = body?.error?.message ?? body?.error ?? body?.message ?? "";
  const why = typeof message === "string" && message ? message : said(body).slice(0, 400);
  if (status === 401) return `Not signed in: ${why}`;
  if (status === 403) return `Your role may not do this: ${why}`;
  return `It did not work (${status}): ${why}`;
}

async function call(catalog: Catalog, person: Person, doors: Doors, name: string, args: Record<string, any>) {
  const workflow = catalog.workflows.find((w) => w.tool === name);
  const record = catalog.records.find((r) => r.find === name || r.get === name);
  if (!workflow && !record) return null;
  if (workflow && !admits(workflow.roles, person)) return { isError: true, content: [{ type: "text", text: "Your role may not run this." }] };
  if (record && !admits(record.roles, person)) return { isError: true, content: [{ type: "text", text: "Your role may not read these records." }] };
  let res: { status: number; body: unknown };
  if (workflow) {
    res = await doors.run(workflow.id, args ?? {});
  } else if (record!.get === name) {
    if (!args?.id) return { isError: true, content: [{ type: "text", text: "`id` is required." }] };
    res = await doors.read(record!.slug, String(args.id), {});
  } else {
    const query: Record<string, string> = {};
    for (const k of ["search", "sort", "order"]) if (args?.[k]) query[k] = String(args[k]);
    query.page = String(Math.max(1, Number(args?.page ?? 1) || 1));
    query.limit = String(Math.min(100, Math.max(1, Number(args?.limit ?? 25) || 25)));
    for (const [k, v] of Object.entries(args?.filters ?? {})) if (!(k in query)) query[k] = String(v);
    res = await doors.read(record!.slug, null, query);
  }
  if (res.status >= 400) return { isError: true, content: [{ type: "text", text: refusal(res.status, res.body) }] };
  const structured = res.body && typeof res.body === "object" && !Array.isArray(res.body) ? res.body : { result: res.body };
  return { content: [{ type: "text", text: said(res.body) }], structuredContent: structured };
}

/** One JSON-RPC message in, its reply out — or null for a notification. */
export async function handle(message: Rpc, catalog: Catalog, person: Person, doors: Doors): Promise<object | null> {
  const id = message?.id;
  if (!message || typeof message !== "object" || typeof message.method !== "string") {
    return fail(id, -32600, "Invalid request");
  }
  const notification = id === undefined;
  const method = message.method;
  if (method.startsWith("notifications/")) return null;
  try {
    if (method === "initialize") {
      const asked = String(message.params?.protocolVersion ?? "");
      return ok(id, {
        protocolVersion: PROTOCOL_VERSIONS.includes(asked) ? asked : PROTOCOL_VERSIONS[0],
        capabilities: { tools: { listChanged: false } },
        serverInfo: { name: catalog.app || "Application", version: "1.0.0" },
        instructions: `${catalog.app}${catalog.about ? ` — ${catalog.about}` : ""}. You act as ${person.email ?? "the signed-in person"}` +
          `${person.role ? ` (${person.role})` : ""}: the tools are what that person may do in the app, and every rule the app has applies.`,
      });
    }
    if (method === "ping") return ok(id, {});
    if (method === "tools/list") return ok(id, { tools: toolsFor(catalog, person) });
    if (method === "tools/call") {
      const name = String(message.params?.name ?? "");
      const result = await call(catalog, person, doors, name, message.params?.arguments ?? {});
      return result ? ok(id, result) : fail(id, -32602, `Unknown tool: ${name}`);
    }
    if (method === "resources/list") return ok(id, { resources: [] });
    if (method === "prompts/list") return ok(id, { prompts: [] });
    return notification ? null : fail(id, -32601, `Method not found: ${method}`);
  } catch (err) {
    return fail(id, -32603, `Internal error: ${String((err as Error)?.message ?? err).slice(0, 300)}`);
  }
}
