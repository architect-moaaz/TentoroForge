"""_resolve_table must resolve an entity to the table name the Drizzle schema
ACTUALLY declares (camelCase via contract_generator._to_table), not a snake_case
derivation. The snake bug produced `knowledge_articles` for `KnowledgeArticle`
while the schema declared `knowledgeArticles` → runtime `[workflow:X] unknown table`.
"""

from services.workflow_generator import _resolve_table


def test_multiword_matches_real_camel_table():
    """Reproduction: multi-word entity resolves to the real camel table, not snake."""
    result = _resolve_table("KnowledgeArticle", ["knowledgeArticles", "tickets"])
    assert result == "knowledgeArticles"
    assert "_" not in result  # never a snake form


def test_multiword_snake_schema_still_matches():
    """If the schema really declared a snake table, return that verbatim."""
    assert _resolve_table("KnowledgeArticle", ["knowledge_articles"]) == "knowledge_articles"


def test_singleword_unchanged():
    assert _resolve_table("Ticket", ["tickets"]) == "tickets"


def test_fallback_no_table_names():
    """No real tables to match → camelCase fallback (schema convention), not snake."""
    assert _resolve_table("KnowledgeArticle", []) == "knowledgeArticles"
