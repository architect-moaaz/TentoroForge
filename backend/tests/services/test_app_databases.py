

def test_the_app_is_given_the_loopback_address_not_localhost(tmp_path):
    from services import app_databases as ad
    assert ad.app_facing("postgresql://u:p@localhost:5432/app_x") == "postgresql://u:p@127.0.0.1:5432/app_x"
    assert ad.app_facing("postgresql://u:p@db.internal:5432/x") == "postgresql://u:p@db.internal:5432/x"
    assert ad.app_facing("postgresql://u:localhost@host/x") == "postgresql://u:localhost@host/x", "only the host"
    ad._write_url(tmp_path, "postgresql://u:p@localhost:5432/app_x")
    assert "@127.0.0.1:5432/app_x" in (tmp_path / ".env.local").read_text("utf-8")


def test_recording_a_dev_server_does_not_crash_where_there_are_no_process_groups(monkeypatch):
    """Windows has no `os.getpgid`: the build's assemble step died on it after everything else had passed."""
    import os
    from services import dev_servers
    monkeypatch.delattr(os, "getpgid", raising=False)
    dev_servers.track(12345, port=4000, root="/tmp/x", kind="boot-check")      # must simply not record
