"""Security headers middleware — adds standard security headers to all responses."""

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Injects security headers and request ID into every response."""

    async def dispatch(self, request: Request, call_next):
        # Generate request ID for tracing
        request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        request.state.request_id = request_id

        response = await call_next(request)

        # The visual editor iframes a generated project's dev server
        # through the /preview/serve reverse proxy. Sending DENY /
        # frame-ancestors 'none' back on those responses would block the
        # iframe outright — this is the one path where the platform
        # legitimately wants a same-origin iframe.
        path = request.url.path
        is_preview_serve = "/preview/serve" in path

        # Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        if not is_preview_serve:
            response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["X-Request-ID"] = request_id

        # HSTS — only enable in production (when not localhost)
        host = request.headers.get("host", "")
        if not host.startswith("localhost") and not host.startswith("127.0.0.1"):
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        # Content Security Policy — permissive for dev, tighter for prod.
        # frame-ancestors omitted on the preview.serve proxy path so the
        # platform editor's iframe can load its own project's Next dev
        # output (see comment above).
        frame_ancestors = "" if is_preview_serve else "; frame-ancestors 'none'"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "font-src 'self' data:; "
            "connect-src 'self' https:"
            f"{frame_ancestors}"
        )

        return response
