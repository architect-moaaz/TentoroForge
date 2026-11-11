"""DITANS QA, 2026-11-05 (DIT-004): a sensitive field is kept as ciphertext
(`<field>_encrypted`) with its plain column empty, so a process reading the
organisation saw no signatory and "Submit for verification" refused every
employer that had named one. The engine opens sealed values when a process
reads a row — a record input or a `db_query` — and a screen still reads masks."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_record_inputs_and_queries_open_sealed_values():
    engine = (ROOT / "templates/runtime/workflows/index.ts").read_text()
    assert "export async function openSealed" in engine
    assert 'key.endsWith("_encrypted")' in engine and "decryptSensitive(blob)" in engine
    assert "return row ? await openSealed(row) : null;" in engine, "a record input is opened"
    assert "queryResult(await Promise.all((rows ?? []).map((r: Record<string, unknown>) => openSealed(r))))" in engine, \
        "a query's rows are opened"
    assert '`${plain}_mask`' in engine, "a value that cannot be opened reads as present, never as empty"
