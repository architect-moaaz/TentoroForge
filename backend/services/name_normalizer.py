"""Single canonical name normalizer for entity name families.

This is the SINGLE place entity names get normalized. It promotes the
canonical trio (`_to_table`/`_to_slug`/`_to_camel`) out of
`contract_generator.py` so no generator derives names independently.

The trio below is copied VERBATIM from
`services/contract_generator.py:217-240` — output must stay byte-compatible
so downstream consumers can switch to this module without churning
non-drifting apps.
"""

import re


def to_slug(name: str) -> str:
    """CamelCase → kebab-case: ExpenseReport → expense-reports"""
    slug = re.sub(r'(?<!^)(?=[A-Z])', '-', name).lower()
    # Pluralize simple cases
    if slug.endswith('y') and not slug.endswith('ey'):
        return slug[:-1] + 'ies'
    if slug.endswith(('s', 'sh', 'ch', 'x', 'z')):
        return slug + 'es'
    return slug + 's'


def to_camel(name: str) -> str:
    """CamelCase → camelCase: ExpenseReport → expenseReport"""
    return name[0].lower() + name[1:]


def to_table(name: str) -> str:
    """CamelCase → table constant name: ExpenseReport → expenseReports"""
    camel = to_camel(name)
    if camel.endswith('y') and not camel.endswith('ey'):
        return camel[:-1] + 'ies'
    if camel.endswith(('s', 'sh', 'ch', 'x', 'z')):
        return camel + 'es'
    return camel + 's'


def to_singular(name: str) -> str:
    """PascalCase → kebab-SINGULAR: ExpenseReport → expense-report.

    Kebab-cases the PascalCase name WITHOUT pluralizing. This is the stable
    join-key id used by relationships/interactions/fks.
    """
    return re.sub(r'(?<!^)(?=[A-Z])', '-', name).lower()


def _hint_to_slug(hint: str) -> str:
    """Kebab-case an explicit table hint for use as the file/route slug.

    camelCase/PascalCase → kebab (`recruitmentDrives` → `recruitment-drives`),
    underscores → dashes, everything lower-cased. The hint's plurality is kept
    verbatim (the hint is authoritative), so an uncountable `equipment` stays
    `equipment` instead of being re-pluralized to `equipments`.
    """
    s = re.sub(r'(?<!^)(?=[A-Z])', '-', hint)
    return s.replace('_', '-').lower()


def name_family(name: str, table_hint: str = None) -> dict:
    """Return the full canonical name family for an entity.

    When `table_hint` is provided it wins for `table` verbatim (NOT
    re-pluralized) — this is how the pipeline stops discarding the planner's
    explicit table name — and the `slug`/`schemaFile`/`typeFile` are derived
    CONSISTENTLY from that same hint (kebab-cased) rather than re-pluralizing
    the display name, so `table` and `slug` name the SAME base. Without a hint
    the byte-compatible `to_table`/`to_slug` derivation is used unchanged.
    """
    if table_hint:
        table = table_hint
        slug = _hint_to_slug(table_hint)
    else:
        table = to_table(name)
        slug = to_slug(name)
    return {
        "id": to_singular(name),
        "name": name,
        "singular": to_camel(name),
        "table": table,
        "slug": slug,
        "camel": to_camel(name),
        "schemaFile": f"src/db/schema/{slug}.ts",
        "typeFile": f"src/types/{slug}.ts",
    }
