"""The trail's insert, the policy it reads, and the readers it unmasks for,
as shipped (60v142ju, 2026-10-12): the changed columns were interpolated as
a list Postgres refused ("malformed array literal"), so a regulated app
recorded nothing; the policy was loaded lazily and read synchronously, so
the audit screen said "no trail"; a clear-text sensitive read was never
recorded; the export's actor was out of scope; the seed read its demo rows
before declaring them; the webhooks route's provider module never shipped."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RT = ROOT / "templates" / "runtime"


def test_the_changed_columns_go_as_json_made_an_array_in_the_query():
    src = (RT / "audit.ts").read_text()
    assert "jsonb_array_elements_text(${changed == null ? null : JSON.stringify(changed)}::jsonb)" in src
    assert "${changed}," not in src


def test_the_policy_is_read_at_load():
    src = (RT / "audit.ts").read_text()
    assert 'import { AUDIT as PROJECTED_AUDIT } from "./audit-policy";' in src
    assert (RT / "audit-policy.ts").is_file()


def test_every_unmasked_read_is_recorded_and_the_export_knows_who_asked():
    engine = (RT / "data-engine.ts").read_text()
    assert "} else if (col in record && allowed && regulated()) {" in engine
    export = (RT / "api-export" / "route.ts").read_text()
    assert "let user: { id?: string; role?: string } | undefined;" in export and "    user = session?.user" in export


def test_the_seed_declares_its_demo_rows_before_reading_them():
    seed = (RT / "seed.ts").read_text()
    assert seed.index("const bag = (isDict(plan.sample_data)") < seed.index("(bag[t.name] as Record<string, unknown>[] | undefined) || []);")


def test_the_provider_adapters_ship_with_the_integrations():
    assert '"providers.ts")' in (ROOT / "services" / "runtime_injector.py").read_text()
