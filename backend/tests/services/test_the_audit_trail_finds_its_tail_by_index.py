"""Every audit write reads the newest row's hash by seq (runtime/audit.ts:
`SELECT hash FROM forge_audit ORDER BY seq DESC LIMIT 1`). Without an index on
seq that is a scan of the whole trail per write: 281 ms at 666k rows on DITANS
Test, and pages that read sensitive fields took 11-50 s (2026-11-14)."""
import re
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[2] / "templates" / "runtime"


def test_the_writer_reads_the_tail_by_seq():
    src = (RUNTIME / "audit.ts").read_text()
    assert "ORDER BY seq DESC LIMIT 1" in src


def test_the_audit_table_indexes_seq():
    schema = (RUNTIME / "db" / "forge-audit.schema.ts").read_text()
    assert re.search(r'(uniqueIndex|index)\("forge_audit_seq_idx"\)\.on\(t\.seq\)', schema)
