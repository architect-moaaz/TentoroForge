

def test_generation_writes_where_the_project_says_it_lives():
    """create_project makes output/<short-id>, git-inits it and records it on
    the row; generation derived output/<uuid> and wrote there instead. Every
    project had two directories — an empty git repo the product knows about,
    and the application it does not — and export_service and git_service both
    operate on the recorded one, so export would ship an empty repository."""
    from pathlib import Path

    from routers.blueprint_generate import _output_dir

    class _P:
        id = "3e436622-8693-4d6b-a242-484064a63c74"
        output_dir = "/tmp/forge-output/6vaj13oh"

    assert _output_dir(_P()) == Path("/tmp/forge-output/6vaj13oh")


def test_a_project_with_no_recorded_directory_still_resolves():
    """Rows created before output_dir was populated fall back, and
    project_root validates the id against traversal."""
    from routers.blueprint_generate import _output_dir

    class _P:
        id = "3e436622-8693-4d6b-a242-484064a63c74"
        output_dir = None

    assert _output_dir(_P()).name == "3e436622-8693-4d6b-a242-484064a63c74"
