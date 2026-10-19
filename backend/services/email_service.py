"""Email service — SendGrid or SMTP integration with template support."""

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from config import (
    SENDGRID_API_KEY,
    SMTP_HOST,
    SMTP_PORT,
    SMTP_USER,
    SMTP_PASSWORD,
    EMAIL_FROM,
    APP_ENV,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Email templates
# ---------------------------------------------------------------------------

TEMPLATES = {
    # The Templates Gallery (services/template_gallery.py). Every value is
    # HTML-escaped by the sender: names and descriptions are people's words.
    "template_review_requested": {
        "subject": "Template to review: {template_name}",
        "html": """
        <h2>A template is waiting for your review</h2>
        <p><strong>{requester}</strong> ({org_name}) asked for <strong>{template_name}</strong>
        (v{version}) to be added to the Templates Gallery.</p>
        <p>{description}</p>
        <p><a href="{review_url}">Review it in Tentoro Forge</a></p>
        """,
    },
    "template_approved": {
        "subject": "{template_name} is in the Templates Gallery",
        "html": """
        <h2>Your template was approved</h2>
        <p>Hi {name}, <strong>{template_name}</strong> is now in the Templates Gallery, where
        every team on Tentoro Forge can start an app from it.</p>
        <p>Note from the reviewer: {note}</p>
        <p><a href="{template_url}">See it in Forge</a></p>
        """,
    },
    "template_changes_requested": {
        "subject": "{template_name} needs changes before it is published",
        "html": """
        <h2>Your template needs a few changes</h2>
        <p>Hi {name}, the Tentoro team reviewed <strong>{template_name}</strong> and asked for
        changes before it goes into the Templates Gallery:</p>
        <blockquote>{note}</blockquote>
        <p>Make the changes, then submit it again.</p>
        <p><a href="{template_url}">Open your template</a></p>
        """,
    },
    "template_removed": {
        "subject": "{template_name} was taken out of the Templates Gallery",
        "html": """
        <h2>Your template is no longer in the Gallery</h2>
        <p>Hi {name}, <strong>{template_name}</strong> was taken out of the Templates Gallery:</p>
        <blockquote>{note}</blockquote>
        <p>Projects already made from it are not affected. You can submit it again.</p>
        <p><a href="{template_url}">Open your template</a></p>
        """,
    },
    "welcome": {
        "subject": "Welcome to Tentoro Forge",
        "html": """
        <h2>Welcome to Tentoro Forge, {name}!</h2>
        <p>Your account has been created. You can now start building enterprise applications with AI.</p>
        <p><a href="{app_url}">Go to Tentoro Forge</a></p>
        """,
    },
    "password_reset": {
        "subject": "Reset your Tentoro Forge password",
        "html": """
        <h2>Password Reset</h2>
        <p>Click the link below to reset your password. This link expires in 1 hour.</p>
        <p><a href="{reset_url}">Reset Password</a></p>
        <p>If you didn't request this, you can safely ignore this email.</p>
        """,
    },
    "org_invitation": {
        "subject": "You've been invited to {org_name} on Tentoro Forge",
        "html": """
        <h2>Organization Invitation</h2>
        <p>{inviter_name} has invited you to join <strong>{org_name}</strong> on Tentoro Forge.</p>
        <p><a href="{invite_url}">Accept Invitation</a></p>
        """,
    },
    "workflow_task_assigned": {
        "subject": "New task assigned: {task_name}",
        "html": """
        <h2>New Workflow Task</h2>
        <p>You have been assigned a new task: <strong>{task_name}</strong></p>
        <p>Workflow: {workflow_name}</p>
        {due_info}
        <p><a href="{task_url}">View Task</a></p>
        """,
    },
    "org_invite": {
        "subject": "{inviter} invited you to {org_name} on Forge",
        "html": """
        <h2>You are invited to {org_name}</h2>
        <p>{inviter} has invited you to join <strong>{org_name}</strong> on Forge as {role}.</p>
        <p>Sign up with this email address and you will find the organisation waiting for you:</p>
        <p><a href="{signup_url}">{signup_url}</a></p>
        """,
    },
    "generation_complete": {
        "subject": "Your app is ready: {project_name}",
        "html": """
        <h2>App Generation Complete</h2>
        <p>Your application <strong>{project_name}</strong> has been generated successfully.</p>
        <p><a href="{project_url}">Open Project</a></p>
        """,
    },
}


def render(tmpl: dict, ctx: dict) -> tuple[str, str]:
    """The subject and the HTML body of one template, filled in.

    VALUES ARE PEOPLE'S WORDS. An organisation or a template is named by
    whoever made it, so each value is escaped for the HTML body — a name like
    `<a href=…>` is text, never a link — and the subject, which is plain text,
    is left unescaped ("R&D Tracker", not "R&amp;D Tracker") but held to one
    line, so a name holding a line break cannot add a header to the message."""
    import html as _html

    subject = " ".join(tmpl["subject"].format_map(SafeDict({k: str(v) for k, v in ctx.items()})).split())
    body = tmpl["html"].format_map(SafeDict({k: _html.escape(str(v), quote=True) for k, v in ctx.items()}))
    return subject, body


async def send_email(
    to: str,
    template: str,
    context: dict | None = None,
) -> bool:
    """Send an email using a named template.

    Args:
        to: Recipient email address
        template: Template name (e.g., 'welcome', 'password_reset')
        context: Template variables to substitute

    Returns:
        True if email was sent successfully
    """
    ctx = context or {}
    tmpl = TEMPLATES.get(template)
    if not tmpl:
        logger.error("Unknown email template: %s", template)
        return False

    subject, html = render(tmpl, ctx)

    if APP_ENV == "development":
        logger.info("DEV EMAIL → to=%s subject=%s", to, subject)
        return True

    if SENDGRID_API_KEY:
        return await _send_via_sendgrid(to, subject, html)
    elif SMTP_HOST:
        # smtplib blocks: on the event loop, one slow mail server froze every
        # request the API was serving until it answered. It runs on a thread.
        import asyncio
        return await asyncio.to_thread(_send_via_smtp, to, subject, html)
    else:
        logger.warning("No email provider configured — email not sent to %s", to)
        return False


async def _send_via_sendgrid(to: str, subject: str, html: str) -> bool:
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers={
                    "Authorization": f"Bearer {SENDGRID_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "personalizations": [{"to": [{"email": to}]}],
                    "from": {"email": EMAIL_FROM},
                    "subject": subject,
                    "content": [{"type": "text/html", "value": html}],
                },
            )
            if resp.status_code in (200, 202):
                logger.info("Email sent via SendGrid to %s", to)
                return True
            logger.error("SendGrid error: %s %s", resp.status_code, resp.text)
            return False
    except Exception as e:
        logger.exception("SendGrid send failed: %s", e)
        return False


def _send_via_smtp(to: str, subject: str, html: str) -> bool:
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = EMAIL_FROM
        msg["To"] = to
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            if SMTP_USER:
                server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)

        logger.info("Email sent via SMTP to %s", to)
        return True
    except Exception as e:
        logger.exception("SMTP send failed: %s", e)
        return False


class SafeDict(dict):
    """Dict that returns the key as placeholder for missing format keys."""

    def __missing__(self, key):
        return f"{{{key}}}"
