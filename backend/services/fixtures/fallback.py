import uuid


_NUMERIC_TYPE_PREFIXES = ("int", "numeric", "decimal", "float", "double", "real", "serial")


def fallback_value(field_name: str, sql_type: str) -> object:
    """Type-correct nonsense for a field whose name/type doesn't match any
    higher-layer rule. Used by the fixtures Layer 3 fallback."""
    t = (sql_type or "").lower().strip()
    if t.startswith("uuid") or field_name.lower() == "id":
        return str(uuid.uuid4())
    if t.startswith(("varchar", "text", "char")) or t == "string":
        return "Lorem ipsum dolor sit amet"
    if t.startswith(_NUMERIC_TYPE_PREFIXES):
        return 0
    if t.startswith(("bool", "tinyint(1)")):
        return False
    if t.startswith(("date", "timestamp", "time")):
        return "2026-01-01T00:00:00Z"
    if t.startswith(("json", "jsonb")):
        return {}
    return None
