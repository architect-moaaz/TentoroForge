"""Publish flow — takes a generated app to a live public URL.

Layout:
    provider.py       — DeployProvider Protocol + DeploySnapshot + DeployEvent
    vercel_client.py  — thin async wrapper on the Vercel REST API
    neon_client.py    — thin async wrapper on the Neon REST API
    snapshot.py       — output_dir → Vercel files[] payload
    env_sync.py       — merge integrations + Neon URL + system vars
    vercel_provider.py — composes the above into a DeployProvider

Spec: docs/superpowers/plans/2026-07-23-generated-app-deploy-vercel.md
"""
