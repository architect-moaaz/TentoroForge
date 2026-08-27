# Slice 1 — `mcp` tool_type in Agent Builder

**Date:** 2026-08-01
**Spec:** [2026-08-01-visual-product-search-mcp-agent.md](../specs/2026-08-01-visual-product-search-mcp-agent.md)
**Branch:** `mcp-tool-node` (fork from `smith-orchestrator-v3`)
**Estimated effort:** 3–5 focused days

---

## What this slice delivers

Every app-agent created via the Agent Builder can call an **MCP server** as a tool node — pick server, pick tool from that server's `tools/list`, wire arguments from other nodes. The code_editor materialises real MCP-client-invoking TypeScript inside the generated Next.js app. Admins register approved MCP servers once (in platform integrations); those servers become pickable across every project in the org.

Value: one platform investment turns every future scrape/search/browser-automation/SaaS-integration into a two-click node — no bespoke per-provider integration slice.

## Non-goals

- Editor UI polish beyond functional (design pass separate)
- Multi-hop tool chaining across MCP servers (single-hop is enough)
- OAuth-flow MCP servers (bearer-token / static-key only in v1)
- Runtime-side prompt-hardening against MCP tool_use loops (agent-graph already handles this)

---

## Task list (TDD-flavoured, atomic, ordered)

### Backend

**T1 — `platform_integrations` gets `mcp_servers` provider category** (½ day)
- Extend `backend/services/platform_integrations.py` provider catalog with a `mcp` kind
- Per-server row: `{name, server_url, transport: stdio|http|sse, auth_kind: none|bearer|apikey_header, auth_secret, enabled}`
- Migration: new `platform_mcp_servers` table (or reuse `platform_integrations.config` jsonb if the shape fits — check first)
- REST endpoints `GET/POST/DELETE /api/orgs/{id}/mcp-servers` (mirror existing integrations pattern)
- Unit tests for CRUD + secret encryption

**T2 — MCP client pool module in Python (for tools/list discovery)** (½ day)
- New `backend/services/mcp_client.py` — thin wrapper that connects to an MCP server, calls `tools/list`, returns typed schema
- Uses `mcp` python SDK (`pip install mcp`) — add to `pyproject.toml`
- Cache result per (server_url, transport) with 5-min TTL — tools rarely change
- Endpoint `GET /api/orgs/{id}/mcp-servers/{server_id}/tools` returns cached list for editor UI
- Unit tests with a mocked MCP server + real Firecrawl integration test (gated behind `FORGE_LIVE_MCP=1`)

**T3 — Agent-builder tool_type accepts `mcp`** (½ day)
- `backend/services/node_config_specs.py` — add `tool_type: mcp` variant with fields `{server_id, tool_name, args_mapping}`
- Validator rejects incomplete mcp tool nodes (missing server or tool)
- `backend/routers/agent_builder.py` save/update endpoints accept the new shape
- Unit tests for validator branch

**T4 — Codegen: `_build_agent_instruction` handles mcp tool nodes** (1 day)
- New branch in `_build_agent_instruction` for `tool_type == "mcp"` — emits instruction to the code_editor:
  > Import `@modelcontextprotocol/sdk`. Instantiate a client for server `{server_url}` using `{transport}` transport with `{auth}` credentials from env `MCP_${server_id}_SECRET`. Register a tool named `{tool_name}` on the agent that maps `{args_mapping}` → `client.callTool()` and returns the result as `{content, isError}`.
- Add an authoritative code exemplar in the prompt so code_editor emits consistent TS every time
- Snapshot test: given a fixture agent JSON with 1 http tool + 1 mcp tool, `_build_agent_instruction` output matches golden file

**T5 — `runtime_injector` writes MCP secrets to `.env.local`** (¼ day)
- `backend/services/runtime_injector.py` — when applying an agent def that includes mcp tools, inject `MCP_${server_id}_SECRET=...` for each referenced server
- Skip disabled servers (surface a warning)
- Unit test with a fake agent def

### Generated-app template

**T6 — Standalone-app template gets `@modelcontextprotocol/sdk` + client pool** (½ day)
- Add `@modelcontextprotocol/sdk` to `backend/templates/standalone-app/package.json.tmpl`
- New file `backend/templates/standalone-app/src/agents/lib/mcpClientPool.ts` — memoised `Map<serverKey, Client>` with reconnect on disconnect, health check on first use, structured error type
- Small helper `callMcpTool(serverKey, toolName, args) → Promise<result>` that agent-service.ts imports
- Vitest for the pool (memoisation, reconnect path, error surfacing)

**T7 — Vendor MCP SDK dist** (¼ day)
- If we vendor other SDKs (check `templates/standalone-app/vendor/`), vendor this one too so first `npm install` on a fresh deploy doesn't hit the network for it
- Otherwise skip

### Frontend (Agent Builder UI)

**T8 — Tool node config: `mcp` option** (½ day)
- `frontend/src/components/agent-builder/ToolNodeConfig.tsx` — add `mcp` to tool_type dropdown
- On select: fetch `/api/orgs/{id}/mcp-servers` → server dropdown
- On server select: fetch `/api/orgs/{id}/mcp-servers/{id}/tools` → tool_name dropdown (with descriptions in tooltip)
- On tool select: render dynamic args-mapping form (each MCP tool exposes a JSON schema for its args)
- Vitest for the component

**T9 — MCP servers admin page** (½ day)
- New `frontend/src/app/settings/mcp-servers/page.tsx` — table of registered servers with add/edit/delete + a "test connection" button that hits `tools/list` and shows count
- Extend the existing `/settings/integrations` sidebar to include this
- E2E-lite: playwright test creating a server + verifying it shows up in the agent-builder tool dropdown

### Acceptance

**T10 — Live E2E on a scratch project** (½ day)
- Register Firecrawl MCP in platform integrations
- Create an agent in the builder: system_prompt + mcp tool node calling `firecrawl.search`
- Apply → generated app has a working `agent-service.ts` + `POST /api/agent/chat`
- curl the endpoint with a query → see real Firecrawl results
- Screenshot / GIF for release notes

**T11 — Documentation snippet** (¼ day)
- Update the Agent Builder section of BLUEPRINT.md
- Small "how to add an MCP server" walkthrough in the platform docs

---

## Sequencing

```
T1 (integration category) ────┐
                              ├─▶ T2 (Python MCP client) ──▶ T3 (spec) ──▶ T4 (codegen)
                              │                                              │
                              │                                              ▼
                              │                                     T5 (env injection)
                              │                                              │
                              ▼                                              │
              T8 (editor UI) ◀────── T2 endpoint                            │
                    │                                                        │
                    ▼                                                        ▼
                   T9 (admin page)                        T6 (runtime pool) + T7 (vendor)
                                                                            │
                                                                            ▼
                                                              T10 (live E2E)
                                                                            │
                                                                            ▼
                                                                T11 (docs)
```

Practical order for one dev: T1 → T3 → T2 → T4 → T5 → T6 → T7 → T8 → T9 → T10 → T11 (backend first because it unblocks the frontend fetches).

## Test gates

| Gate | What must pass | Blocks release? |
|---|---|---|
| Unit tests | `pytest backend/tests/` — new modules only | ✅ |
| Codegen snapshot | Fixture agent → golden instruction file | ✅ |
| Runtime pool tests | `pnpm test` in standalone-app template — new module only | ✅ |
| Live MCP integration | `FORGE_LIVE_MCP=1 pytest -k firecrawl` — hits real Firecrawl | ⚠️ CI-gated, not release-blocking (external dep) |
| Live E2E (T10) | Manual walkthrough, screenshots in release notes | ✅ |

## Rollout

- Ship behind flag `FORGE_MCP_TOOL_TYPE=1` — off by default
- Enable on UAT after T10 passes
- Bake for 2–3 days with internal usage
- Flip on for prod after Slice 2 (vision preset) is also ready, so the first customer app can use both

## Risks

| Risk | Mitigation |
|---|---|
| MCP protocol churn breaks generated code | Pin `@modelcontextprotocol/sdk` version in template; upgrade path is a Smith-fix migration |
| Firecrawl (or chosen server) has rate limits that trip during E2E | Cache tools/list; add per-server call-budget in runtime pool |
| MCP servers with stdio transport need process spawning inside Vercel — not possible | Restrict v1 to `http` + `sse` transports; document stdio-only servers as unsupported |
| Auth secrets leak into agent JSON | Store only `server_id` in agent def; secrets stay in `platform_mcp_servers` + `.env.local` at runtime |
| code_editor generates wrong MCP wiring | Add authoritative code exemplar in prompt (T4); snapshot test catches drift |

## Definition of done

- All T1–T11 committed
- Live E2E (T10) recorded
- Flag `FORGE_MCP_TOOL_TYPE=1` live on UAT
- Slice 2 (vision preset) can begin (no dependency, can start in parallel actually)
- Spec [`2026-08-01-visual-product-search-mcp-agent.md`](../specs/2026-08-01-visual-product-search-mcp-agent.md) §5 checkbox for Slice 1 = done
