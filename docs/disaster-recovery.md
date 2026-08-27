# Disaster Recovery Plan

## Overview

This document outlines the backup strategy, recovery procedures, and RTO/RPO targets for the Tentoro Forge platform.

## RTO / RPO Targets

| Component | RTO (Recovery Time) | RPO (Recovery Point) |
|-----------|--------------------|--------------------|
| Database (PostgreSQL) | 1 hour | 1 hour (with hourly backups) |
| Generated Projects | 4 hours | 24 hours (with daily backups) |
| Redis Cache | N/A (rebuilt on startup) | N/A (ephemeral) |
| Application Containers | 15 minutes | N/A (rebuilt from Git) |

## Backup Strategy

### PostgreSQL Database

**Schedule:** Hourly automated backups via `scripts/backup.sh`

**Method:** `pg_dump` with custom format and compression

**Storage:** Local backup directory + optional S3 upload

**Retention:** 30 days (configurable via `BACKUP_RETENTION_DAYS`)

**Cron example:**
```cron
0 * * * * /app/scripts/backup.sh >> /var/log/backup.log 2>&1
```

### Generated Project Files

**Method:** Generated project files are stored in `/output/` directory. Each project has its own Git repository for version history.

**Backup:** Sync `/output/` to S3 daily or use a managed filesystem with snapshots.

### Application State

**Docker images:** Built and pushed to GHCR on every tagged release. Recovery = pull and deploy.

**Configuration:** All config is in environment variables. Store in a secrets manager (AWS Secrets Manager, Vault, etc.).

## Recovery Procedures

### Database Recovery

1. Stop the application:
   ```bash
   docker compose -f docker-compose.prod.yml stop backend
   ```

2. Restore from backup:
   ```bash
   pg_restore -h localhost -p 5432 -U tentoroforge -d tentoroforge --clean /backups/tentoroforge_YYYYMMDD_HHMMSS.sql.gz
   ```

3. Run any pending migrations:
   ```bash
   cd backend && alembic upgrade head
   ```

4. Restart application:
   ```bash
   docker compose -f docker-compose.prod.yml start backend
   ```

### Full Platform Recovery

1. Provision infrastructure (PostgreSQL, Redis, compute)
2. Deploy containers from latest images
3. Restore database from latest backup
4. Run migrations: `alembic upgrade head`
5. Restore `/output/` from S3 backup
6. Verify health: `curl http://host/ready`

### Redis Recovery

Redis is used for caching and job queues. No backup needed — it rebuilds on startup. In-flight jobs may be lost during a Redis failure; the application handles this gracefully by falling back to inline execution.

## Monitoring

- Health endpoint: `GET /health` (liveness)
- Readiness endpoint: `GET /ready` (DB + Redis connectivity)
- Metrics: `GET /metrics` (Prometheus format)
- Backup monitoring: Check backup script exit code and file size

## Testing

Run a recovery drill quarterly:
1. Create a test project and generate an app
2. Take a backup
3. Destroy the database
4. Restore from backup
5. Verify the project and generated app are intact
