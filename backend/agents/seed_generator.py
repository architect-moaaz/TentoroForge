"""Seed Generator Agent (#9) — generates realistic seed data for the database.

Reads the Drizzle schema, produces a seed.ts file with realistic data,
and executes it against the running PostgreSQL database.
"""

import logging
import os
from typing import AsyncIterator

from services.agent_messages import ClaudeAgentOptions

from services.sdk_agent_runner import query
from services.agent_messages import Message

logger = logging.getLogger(__name__)


SEED_GENERATOR_SYSTEM_PROMPT = r"""You are a seed data generator for Next.js + Drizzle ORM projects.

FIRST: Read `src/contracts/design-spec.json` to understand the domain.
Generate seed data that is DOMAIN-REALISTIC — not generic placeholder text.
Healthcare → real patient names, medical conditions, ICD codes.
Finance → realistic transaction amounts, account types, dates.
E-commerce → real product names, categories, prices.
HR → realistic employee names, departments, job titles.

## YOUR JOB
Read the database schema and seed plan contract, generate realistic and coherent seed data, write it to src/db/seed.ts, and execute it.

## RULES
1. FIRST check if `contracts/seed-plan.json` exists — if so, use it for:
   - Table insertion order (topologically sorted by dependencies)
   - Row counts per table
   - Cross-reference rules (which FK columns reference which tables)
   - Admin user constraints
2. Read the database schema files:
   - Check src/db/schema/ directory for per-entity schema files (preferred)
   - Fall back to src/db/schema.ts if single-file schema
3. Generate seed data that respects:
   - Foreign key ordering: parent tables first, then child tables (use seed-plan order if available)
   - Unique constraints: no duplicate values in unique columns
   - Enum types: only use valid enum values
   - Not-null constraints: provide values for all required columns
4. Use realistic, diverse data:
   - Real-looking names, emails, descriptions
   - Varied but plausible dates
   - Sensible numeric ranges
   - If a theme is given, tailor the data accordingly
5. Write the seed file as src/db/seed.ts using Drizzle's insert API:
   ```ts
   import { db } from './index';
   import { users, posts, ... } from './schema';

   async function seed() {
     // Insert in FK order
     await db.insert(users).values([...]);
     await db.insert(posts).values([...]);
     console.log('Seed complete');
   }

   seed().catch(console.error);
   ```
6. After writing seed.ts, you are DONE. Do NOT execute the seed file.

## CRITICAL RULES
- Do NOT run `npx tsx src/db/seed.ts` or any database commands
- Do NOT try to connect to a database — it is not available during generation
- Just write the seed.ts file with realistic data and stop
- The user will run the seed script when they start their app

## IMPORT RULES
- Import ALL drizzle-orm operators you use: `eq`, `and`, `or`, `sql`, `desc`, `asc`, etc.
  ```ts
  import { eq, and, sql } from "drizzle-orm";  // ← add EVERY operator you reference
  ```
- Import ALL table constants from the schema barrel: `import { users, orders, ... } from "./schema"`
- Read `src/db/schema/index.ts` to see which exports are available — do NOT import tables that don't exist

## DATE RULES
- NEVER build dates from string concatenation with unpadded numbers.
  BAD: `new Date(\`2024-04-${Math.floor(Math.random() * 20) + 1}T10:00:00Z\`)` — produces invalid `2024-04-1T10:00:00Z`
  GOOD: `new Date(2024, 3, day, 10, 0, 0)` — use numeric constructor
  GOOD: `new Date(\`2024-04-${String(day).padStart(2, '0')}T10:00:00Z\`)` — zero-pad if using strings

## IMAGE URL RULES
- NEVER use `https://example.com/image.jpg` — these don't resolve and show broken image icons
- Use real placeholder services:
  - `https://picsum.photos/seed/${id}/400/300` — random realistic photos
  - `https://placehold.co/400x300/EEE/31343C?text=Product+Name` — labeled placeholders
  - `/placeholder.svg` — local fallback

## OUTPUT
Write the seed file and confirm it's ready. Do NOT attempt to execute it.
"""


async def run_seed_generator(
    output_dir: str,
    row_count: int = 10,
    theme: str | None = None,
    db_port: int | None = None,
) -> AsyncIterator[Message]:
    """Run the seed generator agent.

    Yields streaming messages for SSE forwarding.
    """
    # The runtime injector already wrote a deterministic src/db/seed.ts (admin login
    # + demo data from seed-plan.json). It's authoritative and reliable, so skip the
    # LLM seed pass rather than clobber it with a less reliable, login-less version.
    _seed = os.path.join(output_dir, "src", "db", "seed.ts")
    if os.path.exists(_seed):
        logger.info("[Seed] deterministic src/db/seed.ts present — skipping LLM seed generator")
        return

    os.environ.pop("CLAUDECODE", None)

    theme_section = ""
    if theme:
        theme_section = f"\n## Theme\nGenerate data with a {theme} theme — names, descriptions, and content should reflect this theme.\n"

    db_section = ""
    if db_port:
        db_section = f"\n## Database\nThe PostgreSQL database is running on localhost:{db_port} (user: postgres, password: postgres, database: project-specific — check .env.local for DATABASE_URL).\n"

    user_prompt = f"""Generate realistic seed data for this project.

## Requirements
- Generate approximately {row_count} rows per table
- Use realistic, diverse values
{theme_section}{db_section}
## Steps:
1. Check if `contracts/seed-plan.json` exists — if so, read it for table order, row counts, and cross-reference rules
2. Read database schema: check src/db/schema/ directory first (per-entity files), fall back to src/db/schema.ts
3. Read src/db/index.ts to understand the database connection setup
4. Write src/db/seed.ts with the seed data (use seed-plan order if available)

IMPORTANT: Do NOT execute the seed script. The database is not available during generation.
Just write the seed.ts file and stop. The user will run it when they start their app.

Start by checking for the seed-plan contract, then reading the schema."""

    # Prefer the Anthropic SDK (reliable, ~seconds) — the bundled CLI crawls/fails
    # under subscription-auth throttle. Falls back to the CLI when no API key is set.
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            wrote = await _generate_seed_via_sdk(output_dir, row_count, theme)
            logger.info("[Seed] wrote src/db/seed.ts via Anthropic SDK (%d bytes)", wrote)
            return
        except Exception as e:  # fall through to the CLI path on any SDK failure
            logger.warning("[Seed] SDK path failed (%s); falling back to bundled CLI", e)

    options = ClaudeAgentOptions(
        system_prompt=SEED_GENERATOR_SYSTEM_PROMPT,
        allowed_tools=["Write", "Edit", "Read", "Glob"],
        permission_mode="bypassPermissions",
        cwd=output_dir,
        max_turns=8,
        model="claude-haiku-4-5-20251001",
    )

    async for message in query(prompt=user_prompt, options=options):
        yield message


async def _generate_seed_via_sdk(output_dir: str, row_count: int, theme: str | None) -> int:
    """Generate src/db/seed.ts in one Anthropic SDK call. Returns bytes written.

    Reads the real schema files + seed-plan and asks for the COMPLETE seed.ts back as
    code (no agentic Write tool), then writes it. The single round-trip is far more
    reliable than the bundled-CLI agent loop."""
    import asyncio
    import glob
    from services import llm_client  # LangGraph migration (LG-1): ChatAnthropic-backed shim

    root = output_dir
    def _read(p: str) -> str:
        try:
            return open(os.path.join(root, p), encoding="utf-8").read()
        except Exception:
            return ""

    schema_files = sorted(glob.glob(os.path.join(root, "src", "db", "schema", "*.ts")))
    schema_blob = "\n\n".join(
        f"// FILE: src/db/schema/{os.path.basename(f)}\n{open(f, encoding='utf-8').read()}"
        for f in schema_files if os.path.basename(f) not in ("index.ts",)
    ) or _read("src/db/schema.ts")
    seed_plan = _read("contracts/seed-plan.json")
    db_index = _read("src/db/index.ts")

    theme_line = f"Theme: {theme}. Names/descriptions must reflect it.\n" if theme else ""
    prompt = (
        f"Generate the COMPLETE contents of src/db/seed.ts for this Next.js + Drizzle app.\n"
        f"~{row_count} rows per table. {theme_line}\n"
        "Rules:\n"
        "- Cover EVERY table in the schema below — do not skip any.\n"
        "- Insert in foreign-key order (parents before children); use the seed-plan order if present.\n"
        "- Use ONLY columns that exist in the schema below. Match column names exactly.\n"
        "- Generate realistic, coherent, domain-specific values (not 'Item 1').\n"
        "- Keep string/text fields CONCISE (one short sentence max) so the whole file fits.\n"
        "- Wire child rows to real parent ids you inserted (capture returned ids).\n"
        "- Seed an admin user (email admin@example.com) into the auth/users table if one exists.\n"
        "- Import db from './index' (or '@/db') and tables from their schema modules, matching db/index.ts.\n"
        "- End with a self-invoking async main() that runs the inserts and calls process.exit(0).\n\n"
        f"=== contracts/seed-plan.json ===\n{seed_plan or '(none)'}\n\n"
        f"=== src/db/index.ts ===\n{db_index}\n\n"
        f"=== schema ===\n{schema_blob}\n\n"
        "Output ONLY the TypeScript file content (no prose, no markdown fences)."
    )

    client = llm_client.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = await asyncio.wait_for(
        client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=16000,
            system=SEED_GENERATOR_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        ),
        timeout=300,
    )
    text = "".join(b.text for b in msg.content if hasattr(b, "text"))
    # Strip accidental markdown fences.
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    t = t.strip() + "\n"
    out = os.path.join(root, "src", "db", "seed.ts")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(t)
    return len(t)
