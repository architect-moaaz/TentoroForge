"""Security headers middleware — adds standard security headers to all responses."""

import os
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from middleware.phone_paths import is_phone_picture


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
        # The phone preview's built screens (`/phone/serve`) are framed by the same editor,
        # and so is the page an instant page runs in (`/preview/frame`).
        is_preview_serve = "/preview/serve" in path or path.endswith("/preview/frame") or is_phone_picture(path)

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
        # A preview is on an origin of its own (services/preview_origin.py):
        # framed by the platform's editor, and by nothing else.
        if is_preview_serve:
            from services.preview_origin import editor_origins
            frame_ancestors = "; frame-ancestors 'self' " + " ".join(editor_origins())
        else:
            frame_ancestors = "; frame-ancestors 'none'"
        if is_phone_picture(path):
            # THE APP'S CODE RUNS HERE, and the platform keeps its sign-in in `localStorage`. On the platform's own origin a screen's
            # code (or a package's) could read a viewer's token, and the link needs no sign-in, so it can be sent to anyone signed
            # in (PR #28 review, 2026-10-22). `sandbox allow-scripts` (and no `allow-same-origin`) gives the page an origin of its
            # own with no storage and no cookies, WHETHER IT IS FRAMED OR OPENED DIRECTLY; only the platform's own pages may frame it.
            frame_ancestors = "; sandbox allow-scripts; frame-ancestors 'self'"
            response.headers["X-Frame-Options"] = "SAMEORIGIN"
            if request.method in ("GET", "HEAD"):
                # A sandboxed page is a different origin, so its fonts and fetches need this. What is served is public and carries no
                # credentials (the picture is loaded without a sign-in), so `*` gives nothing away.
                response.headers["Access-Control-Allow-Origin"] = "*"
        # AN APP'S OWN FONTS. Its tokens import its typefaces from Google
        # Fonts, as the published app loads them; refused here, every drawn
        # screen in the preview fell back to a serif (DITANS, 2026-10-30).
        app_fonts = (" https://fonts.googleapis.com", " https://fonts.gstatic.com") if is_preview_serve else ("", "")
        # A PAYER PAYS IN THE PREVIEW TOO. Razorpay takes the money in its own
        # Checkout window — its script, and the frames it opens over the app's
        # page; refused here, an owner trying the app's payments with test
        # keys met "Razorpay's checkout could not be loaded" on every payment.
        # Against the local gateway emulator, its stand-in of that window.
        pay_script, pay_frame, pay_connect = "", "", ""
        if is_preview_serve:
            pay_script = " https://checkout.razorpay.com"
            pay_frame = " https://api.razorpay.com https://checkout.razorpay.com"
            emulator = (os.environ.get("FORGE_PAYMENTS_EMULATOR") or "").rstrip("/")
            if emulator:
                pay_script += f" {emulator}"
                pay_connect = f" {emulator}"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            f"script-src 'self' 'unsafe-inline' 'unsafe-eval'{pay_script}; "
            f"style-src 'self' 'unsafe-inline'{app_fonts[0]}; "
            "img-src 'self' data: https:; "
            f"font-src 'self' data:{app_fonts[1]}; "
            f"connect-src 'self' https:{pay_connect}"
            + (f"; frame-src 'self'{pay_frame}" if pay_frame else "")
            + f"{frame_ancestors}"
        )

        return response
