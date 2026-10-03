"""RK_Test (jbih8cj3), 2026-09-28: Create Child inserted patientId "001",
Postgres refused it, the run failed — and the execution log said the step
"completed", the error tucked in its output. The shipped engine is run by
its own suite (`templates/runtime/__tests__/run-step-error-tests.sh`)."""
import subprocess
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[2] / "templates/runtime"


def test_the_shipped_engine_logs_a_step_that_answered_an_error_as_failed():
    out = subprocess.run(["bash", str(RUNTIME / "__tests__/run-step-error-tests.sh")],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stdout[-1500:] + out.stderr[-1500:]
    assert "the log row of the step that answered an error says failed" in out.stdout
