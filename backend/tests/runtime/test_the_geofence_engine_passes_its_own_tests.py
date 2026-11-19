"""The geofence engine and service (templates/runtime/geofence) are TypeScript with their own node:test suites: zone maths,
enter/exit/dwell/approaching, noisy and out-of-order GPS, duplicates, thousands of zones, and the service that records and
announces each crossing once. This runs them with the rest of the tests.
Needs Node 22.6+ (`--experimental-transform-types`); skipped, with the reason, where Node is missing or older."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

GEOFENCE = Path(__file__).resolve().parents[2] / "templates" / "runtime" / "__tests__" / "geofence"


def _node():
    exe = shutil.which("node")
    if not exe:
        return None, "node is not installed"
    out = subprocess.run([exe, "--version"], capture_output=True, text=True).stdout.strip()
    m = re.match(r"v(\d+)\.(\d+)", out)
    if not m or (int(m[1]), int(m[2])) < (22, 6):
        return None, f"node {out} cannot strip types (needs 22.6+)"
    return exe, ""


def test_the_geofence_engine_passes_its_own_tests():
    exe, why = _node()
    if not exe:
        pytest.skip(why)
    r = subprocess.run([exe, "--experimental-transform-types", "--no-warnings", "--import", "./_register.mjs", "--test", "engine.test.ts", "service.test.ts", "rules.test.ts", "hub.test.ts", "plan.test.ts", "privacy.test.ts", "load.test.ts"],
                       cwd=GEOFENCE, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, (r.stdout + r.stderr)[-3000:]
    assert re.search(r"^# pass (\d+)", r.stdout, re.M) and int(re.search(r"^# pass (\d+)", r.stdout, re.M)[1]) >= 77


# ---- whole scenarios: brief -> plan -> app -> simulated phones -> what the rules did ----------------------------------------

A, B = "12.9716, 77.5946", "12.9716, 77.6315"   # 4 km apart
BRIEFS = {
    "delivery": ("Food delivery app. Customers order from restaurants and drivers deliver the order. Alert the customer when the driver is within 300 m. "
                 f"Zone: Restaurant pickup - circle 100 m at {A}. Zone: Customer drop-off - circle 150 m at {B}."),
    "ride": ("Taxi app. Passengers book rides and trips. Notify the passenger when the driver arrives at the pickup point. "
             f"Zone: Pickup point - circle 80 m at {A}. Zone: Drop-off point - circle 120 m at {B}."),
    "fleet": f"Fleet of trucks. Alert when a vehicle leaves the depot. Zone: Depot - circle 250 m at {A}.",
    "attendance": f"Nurses clock in when they arrive on site; attendance and shifts are tracked on the field. Zone: Work site - circle 200 m at {A}.",
    "delivery_unlocated": "Food delivery app. Customers order from restaurants and drivers deliver the order. Alert the customer when the driver is within 300 m.",
}


def test_whole_scenarios_from_a_brief_to_what_the_rules_did(tmp_path):
    import json
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from services.blueprint import geofence_plan as gp

    exe, why = _node()
    if not exe:
        pytest.skip(why)
    for name, brief in BRIEFS.items():
        plan = gp.analyse(brief)
        assert plan.needed, name
        (tmp_path / f"{name}.json").write_text(json.dumps(plan.to_json()), encoding="utf-8")
    env = {**__import__("os").environ, "GEOFENCE_PLANS": str(tmp_path)}
    r = subprocess.run([exe, "--experimental-transform-types", "--no-warnings", "--import", "./_register.mjs", "--test", "scenarios.test.ts"],
                       cwd=GEOFENCE, capture_output=True, text=True, timeout=300, env=env)
    assert r.returncode == 0, (r.stdout + r.stderr)[-4000:]
    m = re.search(r"^# pass (\d+)", r.stdout, re.M)
    assert m and int(m[1]) >= 9 and re.search(r"^# skipped 0", r.stdout, re.M), r.stdout[-800:]
