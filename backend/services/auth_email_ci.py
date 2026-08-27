"""Make the generated app's credentials login case-insensitive + whitespace-tolerant.

The auth agent emits `where(eq(users.email, credentials.email))` — a case-SENSITIVE,
untrimmed lookup. Browsers auto-capitalize `type="email"` fields (e.g. "Admin@…"), so a
user who seeded "admin@example.com" gets `CredentialsSignin` (401) on stage. Rewrite the
lookup to compare lowercased+trimmed values.
"""
from __future__ import annotations

import re
from pathlib import Path

_EQ = re.compile(r"eq\(\s*users\.email\s*,\s*credentials\.email\s*\)")
_CI = "sql`lower(${users.email}) = ${(credentials.email as string).trim().toLowerCase()}`"
_IMPORT = re.compile(r'import\s*\{([^}]*)\}\s*from\s*"drizzle-orm"')


def make_email_login_case_insensitive(output_dir: str | Path) -> dict:
    p = Path(output_dir) / "src" / "auth.ts"
    if not p.exists():
        return {"patched": False, "reason": "no auth.ts"}
    s = p.read_text(encoding="utf-8")
    if "lower(${users.email}" in s:
        return {"patched": False, "reason": "already case-insensitive"}
    if not _EQ.search(s):
        return {"patched": False, "reason": "email lookup pattern not found"}

    # Ensure `sql` is imported from drizzle-orm.
    def _add_sql(m: re.Match) -> str:
        names = m.group(1)
        if re.search(r"\bsql\b", names):
            return m.group(0)
        return 'import { ' + names.strip().rstrip(",") + ', sql } from "drizzle-orm"'

    s2, n = _IMPORT.subn(_add_sql, s, count=1)
    if n == 0 and "from \"drizzle-orm\"" not in s2 or "sql" not in s2:
        if "import { sql }" not in s2 and "lower(${users.email}" not in s2:
            s2 = 'import { sql } from "drizzle-orm";\n' + s2

    s2 = _EQ.sub(_CI, s2)
    p.write_text(s2, encoding="utf-8")
    return {"patched": True}
