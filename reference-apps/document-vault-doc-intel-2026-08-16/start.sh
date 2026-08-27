#!/usr/bin/env bash
# Generated App Startup Script — Usage: ./start.sh
# Boots Postgres (Docker) on a FREE port, migrates, seeds, then runs Next.js.
# Self-contained: picks a non-conflicting DB port at runtime and exports
# DATABASE_URL so every CLI step (drizzle-kit, tsx seed, next) sees the same DB.

set -e

# printf '%b' interprets the \033 colour escapes portably (plain `echo` on macOS
# prints them literally).
say() { printf '%b\n' "$1"; }
GREEN="\033[0;32m"; YELLOW="\033[0;33m"; RED="\033[0;31m"; NC="\033[0m"

# --seed-only: boot Postgres + migrate + seed, then STOP (no dev server). Used by
# the chat "Seed demo data" action to populate the DB and surface the admin login.
SEED_ONLY=0
[ "$1" = "--seed-only" ] && SEED_ONLY=1

say "${GREEN}🚀 Starting generated app...${NC}"

# Derive the DB name from .env.local's DATABASE_URL (segment after the last '/'),
# so it matches the database docker-compose creates. Default: app.
DB_NAME="app"
if [ -f .env.local ]; then
  _u=$(grep -E '^DATABASE_URL=' .env.local 2>/dev/null | head -1 | sed -E 's|.*/([^/?]+).*|\1|' || true)
  [ -n "$_u" ] && DB_NAME="$_u"
fi

# Pick a free host port for Postgres — every generated app otherwise hardcodes
# 5432 and collides the moment a second app is already running.
is_free() {
  if command -v lsof >/dev/null 2>&1; then ! lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
  else ! nc -z localhost "$1" >/dev/null 2>&1; fi
}
DB_PORT="${DB_PORT:-5432}"
if ! is_free "$DB_PORT"; then
  for p in $(seq 5432 5600); do
    if is_free "$p"; then DB_PORT="$p"; break; fi
  done
fi
export DB_PORT
export DATABASE_URL="postgresql://postgres:postgres@localhost:${DB_PORT}/${DB_NAME}"
say "${YELLOW}🔌 Database port: ${DB_PORT} (DATABASE_URL exported)${NC}"

# Write .env (read by docker compose for ${DB_PORT}, and by drizzle-kit which
# auto-loads .env) and sync .env.local's DATABASE_URL (read by next dev) so all
# tools agree on the same port — drizzle-kit/seed do NOT auto-load .env.local.
{ printf 'DB_PORT=%s\n' "$DB_PORT"; printf 'DATABASE_URL=%s\n' "$DATABASE_URL"; } > .env
if [ -f .env.local ]; then
  _tmp=$(mktemp); grep -vE '^DATABASE_URL=' .env.local > "$_tmp" 2>/dev/null || true
  printf 'DATABASE_URL=%s\n' "$DATABASE_URL" >> "$_tmp"; mv "$_tmp" .env.local
fi

# 1. Start PostgreSQL (errors are shown, NOT swallowed).
if [ -f docker-compose.yml ]; then
  say "${YELLOW}📦 Starting PostgreSQL on :${DB_PORT}...${NC}"
  docker compose up -d || docker-compose up -d
  say "${YELLOW}⏳ Waiting for database...${NC}"
  for i in $(seq 1 30); do
    if docker compose exec -T postgres pg_isready -U postgres >/dev/null 2>&1; then
      say "${GREEN}✅ Database is ready${NC}"; break
    fi
    if [ "$i" -eq 30 ]; then say "${RED}❌ Database failed to start — run: docker compose logs${NC}"; exit 1; fi
    sleep 1
  done
else
  say "${YELLOW}ℹ️  No docker-compose.yml — using external DATABASE_URL${NC}"
fi

# 2. Install dependencies
#    --legacy-peer-deps: next-auth@4.24.15 declared a peerOptional bump of
#    nodemailer to ^7 while we pin ^6 (the version our SMTP handler is
#    tested against). Peer-optional means it only matters if you actually
#    use the Email provider — the flag lets npm ignore the noise. Mirrors
#    what vercel.json already does for production deploys.
if [ ! -d node_modules ]; then
  say "${YELLOW}📥 Installing dependencies...${NC}"
  npm install --legacy-peer-deps
  say "${GREEN}✅ Dependencies installed${NC}"
fi

# 3. Migrations (DATABASE_URL exported above → drizzle-kit sees it). --force keeps
#    drizzle-kit push non-interactive; a failed migration is FATAL (no tables = unusable).
if [ -f drizzle.config.ts ]; then
  say "${YELLOW}🔄 Running database migrations...${NC}"
  if npx drizzle-kit push --force; then
    say "${GREEN}✅ Migrations applied${NC}"
  else
    say "${RED}❌ Migration failed — the app needs its tables. Check DATABASE_URL + drizzle.config.ts schema path.${NC}"
    exit 1
  fi
fi

# 4. Seed (non-fatal; errors surfaced).
if [ -f src/db/seed.ts ]; then
  say "${YELLOW}🌱 Seeding database...${NC}"
  if npx tsx src/db/seed.ts; then
    say "${GREEN}✅ Database seeded${NC}"
  else
    say "${YELLOW}⚠️  Seeding failed (continuing) — login/seed data may be missing.${NC}"
  fi
fi

# --seed-only stops here: DB is up + seeded, admin login is ready.
if [ "$SEED_ONLY" = "1" ]; then
  say ""
  say "${GREEN}✅ Seed complete. Admin login:${NC}"
  say "${GREEN}   email:    ${SEED_ADMIN_EMAIL:-admin@example.com}${NC}"
  say "${GREEN}   password: ${SEED_ADMIN_PASSWORD:-admin1234}${NC}"
  say "SEEDED_OK"
  exit 0
fi

# 5. Start dev server
say ""
say "${GREEN}🌐 Starting Next.js dev server...${NC}"
say "${GREEN}   App:      http://localhost:3000${NC}"
say "${GREEN}   Database: localhost:${DB_PORT}${NC}"
say ""
npx next dev
