import inspect

from agents.domain_agent import _DISCOVERY_MAX_TOKENS, run_domain_discovery


def test_discovery_max_tokens_is_generous_enough_to_avoid_truncation():
    # A rich domain dossier (entities + personas + workflows + compliance) blew past
    # the old 4096 cap and got truncated mid-JSON, so _extract_json_object could never
    # find a balanced object. Keep a generous ceiling so the dossier isn't cut off.
    assert _DISCOVERY_MAX_TOKENS >= 8192


def test_discovery_timeout_covers_full_dossier_plus_web_search():
    # The bigger token ceiling means the model writes the full dossier and still runs
    # web searches — that needs well over the original 90s, or it raises TimeoutError.
    default = inspect.signature(run_domain_discovery).parameters["timeout_seconds"].default
    assert default >= 240
