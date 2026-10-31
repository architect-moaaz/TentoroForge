"""A big app is waited for as long as Vercel builds it (DITANS, forge-v3, 2026-10-31).

DITANS — 400 pages, 8,000 files — was declared "Deployment timed out after 300
seconds" while Vercel was still compiling it; the build went on with nobody
watching. Vercel ends an overlong build itself (ERROR), so Forge waits as long."""
from services.deploy import vercel_provider


def test_the_wait_is_vercels_own_build_limit():
    assert vercel_provider._POLL_CEILING_S >= 45 * 60
