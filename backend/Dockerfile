FROM python:3.12-slim AS base

WORKDIR /app

# Install system dependencies.
# `git` is required at runtime: every generated app is committed to its
# own git repo (services/git_service.py) so History reflects real state.
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev git curl ca-certificates gnupg xz-utils && \
    rm -rf /var/lib/apt/lists/*

# Node.js 20 LTS — required by preview.start_preview() which spawns
# `npx next dev` for each project's live-editor preview. Without Node
# in the image, the visual editor's iframe has nothing to load and
# gives 404 in the platform UI (bug B-013).
#
# Using the official prebuilt tarball rather than the NodeSource apt repo
# — the latter sometimes fails on new Debian codenames (`nodistro`) that
# aren't yet in NodeSource's index, and pinning here means the CI image
# stays reproducible across Debian upgrades.
ARG NODE_VERSION=20.18.1
RUN ARCH=$(dpkg --print-architecture) && \
    case "$ARCH" in \
      amd64) NODE_ARCH=x64 ;; \
      arm64) NODE_ARCH=arm64 ;; \
      *) echo "unsupported arch: $ARCH" >&2; exit 1 ;; \
    esac && \
    curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz" \
      -o /tmp/node.tar.xz && \
    tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1 --no-same-owner && \
    rm /tmp/node.tar.xz && \
    node --version && npm --version

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# THE BROWSER THE BUILD LOOKS AT PAGES WITH. `page_look` renders every page
# as it is written and `page_review` every page of the built app, both in
# headless Chromium through Playwright; without the browser in the image
# every look is "unavailable" and pages ship unseen, as they did before it.
# Installed to a path the non-root user below can read (the default is
# root's own cache), with the system libraries Chromium needs.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN playwright install --with-deps chromium && chmod -R a+rX /ms-playwright

# Copy application code
COPY . .

# WHAT THE EDITOR'S SCRIPTS IMPORT, WHERE NODE LOOKS FOR IT. `static/*.mjs`
# parse and rewrite a page's React source with @babel/parser; on a developer's
# machine those resolve from the repo root's node_modules, and in this image
# there is no repo root — so every attempt to open a page in the editor
# answered "Cannot find package '@babel/parser'" (UAT, both stacks).
RUN cd /app/static && npm install --omit=dev --no-audit --no-fund --no-package-lock

# Create output directory
RUN mkdir -p /app/output

# Non-root user
RUN adduser --disabled-password --gecos '' appuser && \
    chown -R appuser:appuser /app
USER appuser

EXPOSE 6500

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:6500/health')" || exit 1

# Migrate then serve. `alembic upgrade head` is idempotent — safe to
# re-run on every container start, and prevents "fresh disk boots
# without schema" surprises on new instances.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn main:app --host 0.0.0.0 --port 6500 --workers 2"]
