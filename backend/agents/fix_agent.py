"""Fix Agent — diagnoses and repairs runtime errors in generated apps.

Full-scope agent: reads the failing file, its imports, surrounding types,
and API routes to understand context before applying a targeted fix.
"""

import os
from typing import AsyncIterator

from services.agent_messages import ClaudeAgentOptions

from services.sdk_agent_runner import query
from services.agent_messages import Message


FIX_AGENT_SYSTEM_PROMPT = r"""You are a senior React/Next.js debugger. You fix runtime errors in generated Next.js 15 applications.

Before fixing, read `src/contracts/design-spec.json` to understand the design system and domain context.
Your fixes should maintain the design intent — don't strip styling to make something compile.

## YOUR JOB
You receive an error report with:
- Error message and type
- File path and line number
- Stack trace
- Source code context

You must:
1. Read the failing file to understand the full context
2. Read any imported files if needed (types, components, API client)
3. Diagnose the ROOT CAUSE — not just the symptom
4. Apply a MINIMAL, TARGETED fix using the Edit tool — do NOT rewrite entire files

## COMMON ERROR PATTERNS

### "X is not defined" / "Cannot access X before initialization"
- Variable used before its `useState` declaration → move `useState` above first usage
- Variable referenced in useQuery queryKey but never declared → remove from queryKey
- Import missing → add the import

### "Invalid hook call"
- Hook called outside component body (e.g., at module level)
- Hook called inside a callback, loop, or condition
- Multiple React copies (check package.json)

### "No QueryClient set"
- Missing QueryClientProvider in root layout
- Create a providers.tsx with QueryClientProvider, wrap layout body

### "Cannot find module X"
- Missing npm dependency → check if it's in package.json, if not suggest install
- Wrong import path → fix the path
- Component file doesn't exist → check what's available with Glob

### "X is not a function" / "Cannot read properties of undefined"
- Wrong API shape assumption — read the actual API route to see the response shape
- Missing null check — add optional chaining (?.)
- Wrong export type — named vs default export

### Hydration errors
- Client-only code in server component → add "use client"
- Date/random values rendered differently on server vs client → wrap in useEffect

## RULES
1. ALWAYS read the failing file first
2. Only modify the MINIMUM needed to fix the error
3. Do NOT refactor, improve, or clean up surrounding code
4. Do NOT add comments explaining the fix
5. If the fix requires a new file (e.g., providers.tsx), create it
6. After fixing, verify by reading the fixed file to confirm correctness
7. If you cannot determine the fix confidently, say so — do NOT guess
"""


async def run_fix_agent(
    output_dir: str,
    error_info: dict,
    domain: str = "",
) -> AsyncIterator[Message]:
    """Diagnose and fix a runtime error.

    Args:
        output_dir: Project output directory (agent cwd)
        error_info: Error details from the frontend:
            - message: Error message string
            - file: Relative file path (e.g. "src/app/users/page.tsx")
            - line: Line number
            - column: Column number
            - stack: Stack trace string
            - type: Error type ("runtime", "unhandled_rejection", "nextjs_overlay")

    Yields:
        Streaming messages for progress tracking.
    """
    os.environ.pop("CLAUDECODE", None)

    message = error_info.get("message", "Unknown error")
    file = error_info.get("file", "")
    line = error_info.get("line", 0)
    stack = error_info.get("stack", "")
    error_type = error_info.get("type", "runtime")

    # Build a focused prompt
    file_instruction = ""
    if file:
        file_instruction = f"\n**Start by reading `{file}`** to see the full context around line {line}."
    else:
        # Try to extract file from stack trace
        file_instruction = "\nExtract the file path from the stack trace and read it first."

    prompt = f"""## Runtime Error Report

**Error**: {message}
**Type**: {error_type}
**File**: {file or "unknown"}
**Line**: {line}
**Stack Trace**:
```
{stack[:2000]}
```
{file_instruction}

## Steps
1. Read the failing file
2. If the error references imports or types, read those too (use Glob to find them)
3. Identify the ROOT CAUSE
4. Apply a minimal fix using Edit
5. Read the file after fixing to verify

Fix this error now."""

    options = ClaudeAgentOptions(
        system_prompt=FIX_AGENT_SYSTEM_PROMPT,
        allowed_tools=["Read", "Edit", "Write", "Glob", "Grep"],
        permission_mode="bypassPermissions",
        cwd=output_dir,
        max_turns=10,
        model="claude-sonnet-4-6",
    )

    async for msg in query(prompt=prompt, options=options):
        yield msg
