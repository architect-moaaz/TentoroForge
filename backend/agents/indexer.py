"""Indexer Agent — reads source files and produces app-model.json."""

import os
from typing import AsyncIterator

from services.agent_messages import ClaudeAgentOptions

from services.sdk_agent_runner import query
from services.agent_messages import Message


INDEXER_SYSTEM_PROMPT = r"""You are a code indexer that analyzes Next.js + TypeScript projects and produces a structured app model.

## YOUR JOB
Read the source files of a project and produce/update `app-model.json` — a structured representation of the application.

## app-model.json SCHEMA
```json
{
  "name": "App Name",
  "description": "Brief description",
  "database": {
    "tables": [
      {
        "name": "table_name",
        "columns": [
          {"name": "id", "type": "serial", "primaryKey": true},
          {"name": "field", "type": "varchar", "nullable": false}
        ],
        "relations": [
          {"type": "one-to-many", "target": "other_table", "foreignKey": "other_id"}
        ]
      }
    ]
  },
  "api": {
    "routes": [
      {"method": "GET", "path": "/api/resource", "description": "List resources"},
      {"method": "POST", "path": "/api/resource", "description": "Create resource"}
    ]
  },
  "pages": [
    {"path": "/", "component": "HomePage", "description": "Dashboard"},
    {"path": "/resource", "component": "ResourceListPage", "description": "Resource list"}
  ],
  "components": [
    {"name": "ResourceTable", "file": "src/components/ResourceTable.tsx", "description": "Data table"}
  ]
}
```

## MERGE WITH CONTRACT
If `src/contracts/app-model.json` exists, read it FIRST and use it as the base.
The contract version contains a dependency graph (entities with depends_on/used_by).
Merge your findings into this structure — preserve the dependency graph fields and
add any newly discovered tables, routes, pages, or components.

## RULES
- Read ALL source files to build a complete picture
- Include EVERY table, API route, page, and significant component
- Descriptions should be concise but informative
- Write the result as `app-model.json` in the project root
- If src/contracts/app-model.json exists, merge its dependency graph data into the output
"""


async def run_indexer(output_dir: str) -> AsyncIterator[Message]:
    """Run the indexer agent to produce app-model.json.

    Yields streaming messages for SSE forwarding.
    """
    os.environ.pop("CLAUDECODE", None)

    user_prompt = """Analyze this project and produce app-model.json.

## Steps:
1. Check if src/contracts/app-model.json exists — if so, read it as the base (preserve dependency graph)
2. Read package.json to understand dependencies
3. Read the database schema (src/db/schema/ directory or src/db/schema.ts)
4. Read all API routes (src/app/api/)
5. Read all pages (src/app/)
6. Read key components
7. Write app-model.json with the complete app model (merged with contract data if available)

Start by checking for the contracts file, then listing all files with Glob."""

    options = ClaudeAgentOptions(
        system_prompt=INDEXER_SYSTEM_PROMPT,
        allowed_tools=["Write", "Read", "Bash", "Glob"],
        permission_mode="bypassPermissions",
        cwd=output_dir,
        max_turns=15,
        model="claude-haiku-4-5-20251001",
    )

    async for message in query(prompt=user_prompt, options=options):
        yield message
