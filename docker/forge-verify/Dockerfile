# Forge Self-Verify Pass runner — headless Chromium behind a Fastify HTTP API.
#
# Base image ships Playwright 1.48 + browsers preinstalled so `docker up` is
# fast. Node 20 (the version Playwright 1.48 supports; matches the platform
# runtime elsewhere). Alpine variants don't work — Playwright needs glibc.
FROM mcr.microsoft.com/playwright:v1.48.0-jammy

WORKDIR /app

# Install dependencies first for layer caching. npm ci needs both files.
COPY package.json package-lock.json* ./
# Install ALL deps (incl. dev) so tsc + vitest are available at build time.
# Prune to prod-only AFTER the compile step so the final image stays lean.
RUN npm install --no-audit --no-fund

# TypeScript sources + config
COPY tsconfig.json ./
COPY src ./src

# Compile TS → dist so runtime starts fast (no tsx overhead).
RUN ./node_modules/.bin/tsc -p .

# Now prune dev deps — dist/ is what runtime loads.
RUN npm prune --omit=dev

ENV NODE_ENV=production
ENV PORT=6600
EXPOSE 6600

# Fastify + browser pool warm-up happens at import time.
CMD ["node", "dist/server.js"]
