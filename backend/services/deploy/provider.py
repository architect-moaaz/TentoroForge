"""DeployProvider — the abstract seam that hides target-specific plumbing.

Every provider (VercelDeployProvider, AwsDeployProvider…) implements the
same async-generator `publish()` method and yields DeployEvent objects.
The router streams those events verbatim to the editor UI over SSE. The
provider owns talking to the actual API (Vercel, AWS, whatever) and
mutating the Deployment row.

Contract:
  - publish() MUST end with a DeployEvent whose stage is "done" (data.url
    set) or "error" (message set). No open-ended streams.
  - publish() MUST persist the Deployment row's status transitions —
    the router doesn't touch the DB during publish.
  - Any exception mid-publish MUST be caught and translated into a
    stage="error" event; never let a raw traceback leak to the UI.

Adding AWS later means implementing this Protocol against CodeBuild /
ECR / App Runner / Aurora / Route 53. The router, SSE, deployments
table, publish button, and history UI stay unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator, Literal, Optional, Protocol, runtime_checkable

DeployStage = Literal[
    "snapshot",       # packing app source into the upload payload
    "provision_db",   # creating / reusing the app's Postgres database
    "migrate",        # running drizzle-kit push (usually at build time)
    "upload",         # transferring the source to the target
    "build",          # target-side build (next build, docker build, …)
    "activate",       # rolling the new version to production
    "done",           # terminal success — data.url must be set
    "error",          # terminal failure — message must be set
]


@dataclass
class DeployEvent:
    """One stage tick, streamed to the editor as an SSE frame.

    `progress` is optional 0..1 within the stage — the UI shows a bar
    for stages that report it, a spinner otherwise. `data` carries the
    terminal payload (url on done, extra context on any stage).
    """

    stage: DeployStage
    message: str
    progress: Optional[float] = None
    data: Optional[dict] = None


@dataclass
class DeploySnapshot:
    """Everything a provider needs to publish an app.

    Assembled by the router from Project + PlatformIntegration rows,
    then handed to the provider. `existing_deployment_id` is set on
    redeploy so the provider can reuse the same Vercel project + Neon
    database instead of creating fresh ones (which would orphan the
    previous deployment).
    """

    project_id: str
    project_slug: str
    output_dir: str
    integrations: dict[str, str] = field(default_factory=dict)
    existing_deployment_id: Optional[str] = None
    triggered_by: Optional[str] = None  # platform user id, for audit


@runtime_checkable
class DeployProvider(Protocol):
    """Every deploy target implements this. Currently: Vercel; later: AWS.

    Made runtime_checkable so the router's provider registry can validate
    concrete implementations at import time.
    """

    name: str

    def publish(self, snapshot: DeploySnapshot) -> AsyncIterator[DeployEvent]:
        """Publish an app to this target. See module-level contract."""
        ...

    async def destroy(self, deployment_id: str) -> None:
        """Tear down all resources for a deployment (Vercel project +
        Neon database, or the AWS equivalent). Called when a user
        deletes their project."""
        ...
