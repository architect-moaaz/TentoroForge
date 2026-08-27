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
    "generation_complete": {
        "subject": "Your app is ready: {project_name}",
        "html": """
        <h2>App Generation Complete</h2>
        <p>Your application <strong>{project_name}</strong> has been generated successfully.</p>
        <p><a href="{project_url}">Open Project</a></p>
        """,
    },
}


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

    subject = tmpl["subject"].format_map(SafeDict(ctx))
    html = tmpl["html"].format_map(SafeDict(ctx))

    if APP_ENV == "development":
        logger.info("DEV EMAIL → to=%s subject=%s", to, subject)
        return True

    if SENDGRID_API_KEY:
        return await _send_via_sendgrid(to, subject, html)
    elif SMTP_HOST:
        return _send_via_smtp(to, subject, html)
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
