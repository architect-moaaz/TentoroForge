from agents.business_logic_agent import _BIZLOGIC_ALLOWED_TOOLS
from agents.api_agent import _API_ALLOWED_TOOLS


def test_bizlogic_cannot_run_blocking_shell_commands():
    # Bash is removed so the agent can't run `npx tsc`/`npm`/`next build` — those go
    # silent for minutes (no streamed events) and trip the 600s IDLE timeout (GF-6).
    # Typechecking belongs in the later QA phase, not mid-generation.
    assert "Bash" not in _BIZLOGIC_ALLOWED_TOOLS
    assert set(_BIZLOGIC_ALLOWED_TOOLS) == {"Write", "Edit", "Read", "Glob"}


def test_api_agent_cannot_run_blocking_shell_commands():
    # The API agent shares the parallel barrier with BusinessLogic and had the same
    # `npx tsc` step — same idle-stall risk. Bash removed for the same reason.
    assert "Bash" not in _API_ALLOWED_TOOLS
    assert set(_API_ALLOWED_TOOLS) == {"Write", "Edit", "Read", "Glob"}
