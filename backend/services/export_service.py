"""Export & deployment helpers — Dockerfile, docker-compose, README, env, git push."""

import asyncio
import uuid
from pathlib import Path
from textwrap import dedent

from sqlalchemy.ext.asyncio import AsyncSession

from services.project_service import get_project_with_auth


# ---------------------------------------------------------------------------
# Dockerfile
# ---------------------------------------------------------------------------

def generate_dockerfile(app_name: str = "app") -> str:
    """Create a multi-stage Dockerfile for a Next.js application."""
    return dedent(f"""\
        # ---- Stage 1: Install dependencies ----
        FROM node:20-alpine AS deps
        WORKDIR /app
        COPY package.json package-lock.json* yarn.lock* pnpm-lock.yaml* ./
        RUN \\
          if [ -f pnpm-lock.yaml ]; then \\
            corepack enable pnpm && pnpm install --frozen-lockfile; \\
          elif [ -f yarn.lock ]; then \\
            yarn install --frozen-lockfile; \\
          else \\
            npm ci; \\
          fi

        # ---- Stage 2: Build the application ----
        FROM node:20-alpine AS builder
        WORKDIR /app
        COPY --from=deps /app/node_modules ./node_modules
        COPY . .
        ENV NEXT_TELEMETRY_DISABLED=1
        RUN \\
          if [ -f pnpm-lock.yaml ]; then \\
            corepack enable pnpm && pnpm run build; \\
          elif [ -f yarn.lock ]; then \\
            yarn build; \\
          else \\
            npm run build; \\
          fi

        # ---- Stage 3: Production runner ----
        FROM node:20-alpine AS runner
        WORKDIR /app
        ENV NODE_ENV=production
        ENV NEXT_TELEMETRY_DISABLED=1

        RUN addgroup --system --gid 1001 nodejs && \\
            adduser --system --uid 1001 nextjs

        # Copy built assets
        COPY --from=builder /app/public ./public
        COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
        COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

        USER nextjs
        EXPOSE 3000
        ENV PORT=3000
        ENV HOSTNAME="0.0.0.0"

        CMD ["node", "server.js"]
    """)


# ---------------------------------------------------------------------------
# docker-compose.yml
# ---------------------------------------------------------------------------

def generate_docker_compose(app_name: str = "app") -> str:
    """Create a docker-compose.yml with PostgreSQL and the Next.js app."""
    safe_name = app_name.lower().replace(" ", "-").replace("_", "-")[:32]
    return dedent(f"""\
        version: "3.9"

        services:
          db:
            image: postgres:16-alpine
            restart: unless-stopped
            environment:
              POSTGRES_DB: ${{POSTGRES_DB:-{safe_name}}}
              POSTGRES_USER: ${{POSTGRES_USER:-postgres}}
              POSTGRES_PASSWORD: ${{POSTGRES_PASSWORD:-changeme}}
            ports:
              - "${{DB_PORT:-5432}}:5432"
            volumes:
              - pgdata:/var/lib/postgresql/data
            healthcheck:
              test: ["CMD-SHELL", "pg_isready -U ${{POSTGRES_USER:-postgres}}"]
              interval: 5s
              timeout: 3s
              retries: 5

          app:
            build:
              context: .
              dockerfile: Dockerfile
            restart: unless-stopped
            ports:
              - "${{APP_PORT:-3000}}:3000"
            environment:
              DATABASE_URL: postgres://${{POSTGRES_USER:-postgres}}:${{POSTGRES_PASSWORD:-changeme}}@db:5432/${{POSTGRES_DB:-{safe_name}}}
              NEXTAUTH_SECRET: ${{NEXTAUTH_SECRET:-please-change-me}}
              NEXTAUTH_URL: ${{NEXTAUTH_URL:-http://localhost:3000}}
              NODE_ENV: production
            depends_on:
              db:
                condition: service_healthy
            healthcheck:
              test: ["CMD", "wget", "--spider", "-q", "http://localhost:3000/api/health"]
              interval: 10s
              timeout: 5s
              retries: 3
              start_period: 30s

        volumes:
          pgdata:
    """)


# ---------------------------------------------------------------------------
# .env.example
# ---------------------------------------------------------------------------

def generate_env_example(app_name: str = "app") -> str:
    """Create a documented .env.example file."""
    safe_name = app_name.lower().replace(" ", "-").replace("_", "-")[:32]
    return dedent(f"""\
        # =============================================================================
        # Environment Variables — {app_name}
        # =============================================================================
        # Copy this file to .env and fill in the values.

        # ---- Database ----
        POSTGRES_DB={safe_name}
        POSTGRES_USER=postgres
        POSTGRES_PASSWORD=changeme
        DATABASE_URL=postgres://postgres:changeme@localhost:5432/{safe_name}

        # ---- Ports ----
        APP_PORT=3000
        DB_PORT=5432

        # ---- Auth ----
        NEXTAUTH_SECRET=generate-a-random-secret-here
        NEXTAUTH_URL=http://localhost:3000

        # ---- Optional: External services ----
        # SMTP_HOST=
        # SMTP_PORT=587
        # SMTP_USER=
        # SMTP_PASSWORD=
        # S3_BUCKET=
        # S3_REGION=
        # S3_ACCESS_KEY=
        # S3_SECRET_KEY=
    """)


# ---------------------------------------------------------------------------
# README.md
# ---------------------------------------------------------------------------

def generate_readme(
    app_name: str = "My App",
    description: str | None = None,
) -> str:
    """Create a README.md with setup instructions."""
    desc_section = description or "A Next.js application generated by Tentoro Forge."

    return dedent(f"""\
        # {app_name}

        {desc_section}

        ## Tech Stack

        - **Framework:** Next.js 14 (App Router)
        - **UI:** React, Tailwind CSS, shadcn/ui
        - **Database:** PostgreSQL
        - **Language:** TypeScript

        ## Getting Started

        ### Prerequisites

        - Node.js 20+
        - npm / yarn / pnpm
        - PostgreSQL 15+ (or Docker)

        ### Local Development

        ```bash
        # 1. Install dependencies
        npm install

        # 2. Copy environment variables
        cp .env.example .env
        # Edit .env with your database credentials

        # 3. Run database migrations (if applicable)
        npx prisma migrate dev   # or: npx drizzle-kit push

        # 4. Start the dev server
        npm run dev
        ```

        Open [http://localhost:3000](http://localhost:3000) in your browser.

        ### Docker Deployment

        ```bash
        # 1. Copy environment variables
        cp .env.example .env
        # Edit .env with production values

        # 2. Build and start containers
        docker compose up -d --build

        # 3. View logs
        docker compose logs -f app
        ```

        The app will be available at [http://localhost:3000](http://localhost:3000).

        ## Environment Variables

        | Variable | Description | Default |
        |---|---|---|
        | `DATABASE_URL` | PostgreSQL connection string | `postgres://postgres:changeme@localhost:5432/{app_name.lower().replace(' ', '-')}` |
        | `NEXTAUTH_SECRET` | Random secret for session encryption | (required) |
        | `NEXTAUTH_URL` | Public URL of the app | `http://localhost:3000` |
        | `APP_PORT` | Port to expose the app | `3000` |
        | `DB_PORT` | Port to expose PostgreSQL | `5432` |

        See `.env.example` for the full list.

        ## Database Setup

        ### Using Docker (recommended)

        The `docker-compose.yml` includes a PostgreSQL service. Data is persisted
        in a named Docker volume (`pgdata`).

        ```bash
        # Start only the database
        docker compose up -d db

        # Connect via psql
        docker compose exec db psql -U postgres
        ```

        ### Manual Setup

        ```bash
        createdb {app_name.lower().replace(' ', '-')}
        # Then update DATABASE_URL in your .env
        ```

        ## Project Structure

        ```
        .
        ├── src/
        │   ├── app/          # Next.js App Router pages
        │   ├── components/   # React components
        │   └── lib/          # Utilities, API clients
        ├── public/           # Static assets
        ├── prisma/           # Database schema & migrations
        ├── Dockerfile        # Multi-stage production build
        ├── docker-compose.yml
        └── .env.example
        ```

        ---
        Built with [Tentoro Forge](https://tentoroforge.dev)
    """)


# ---------------------------------------------------------------------------
# Git push to remote
# ---------------------------------------------------------------------------

async def push_to_git(
    output_dir: str,
    repo_url: str,
    branch: str = "main",
    token: str | None = None,
) -> dict:
    """
    Push the generated project code to an external git repository.

    If a token is provided and the repo_url is HTTPS, the token is injected
    into the URL for authentication (e.g. GitHub PAT).
    """
    from services.git_service import git_init, git_commit

    output_path = Path(output_dir)
    if not output_path.exists():
        raise FileNotFoundError(f"Output directory not found: {output_dir}")

    # Ensure git is initialised and has an initial commit
    await git_init(output_dir)
    commit_hash = await git_commit(output_dir, "Initial commit — generated by Tentoro Forge",
                                   actor="generator")   # S24-9

    # Build authenticated URL if token provided
    auth_url = repo_url
    if token and repo_url.startswith("https://"):
        # Insert token into URL: https://<token>@github.com/...
        auth_url = repo_url.replace("https://", f"https://{token}@", 1)

    # Check if remote 'origin' exists; update or add
    proc = await asyncio.create_subprocess_exec(
        "git", "remote", "get-url", "origin",
        cwd=output_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()

    if proc.returncode == 0:
        # Remote exists — update it
        proc = await asyncio.create_subprocess_exec(
            "git", "remote", "set-url", "origin", auth_url,
            cwd=output_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
    else:
        # Add remote
        proc = await asyncio.create_subprocess_exec(
            "git", "remote", "add", "origin", auth_url,
            cwd=output_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

    # Push to the specified branch
    proc = await asyncio.create_subprocess_exec(
        "git", "push", "-u", "origin", f"HEAD:{branch}", "--force",
        cwd=output_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        error_msg = stderr.decode().strip() or stdout.decode().strip()
        raise RuntimeError(f"Git push failed: {error_msg}")

    # Clean up auth token from remote URL (store plain URL)
    if token and repo_url.startswith("https://"):
        await asyncio.create_subprocess_exec(
            "git", "remote", "set-url", "origin", repo_url,
            cwd=output_dir,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

    return {
        "success": True,
        "branch": branch,
        "repo_url": repo_url,
        "commit_hash": commit_hash,
    }


# ---------------------------------------------------------------------------
# Production bundle — write all deployment files into project
# ---------------------------------------------------------------------------

def write_production_bundle(
    output_dir: str,
    app_name: str = "app",
    description: str | None = None,
) -> list[str]:
    """
    Write Dockerfile, docker-compose.yml, .env.example, and README.md
    into the project output directory. Returns list of files written.
    """
    output_path = Path(output_dir)
    if not output_path.exists():
        raise FileNotFoundError(f"Output directory not found: {output_dir}")

    files_written = []

    files = {
        "Dockerfile": generate_dockerfile(app_name),
        "docker-compose.yml": generate_docker_compose(app_name),
        ".env.example": generate_env_example(app_name),
        "README.md": generate_readme(app_name, description),
    }

    for filename, content in files.items():
        filepath = output_path / filename
        filepath.write_text(content)
        files_written.append(filename)

    return files_written
