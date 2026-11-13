# Production Deployment & Operations Runbook

This guide details the production deployment, security configuration, disaster recovery, and operational procedures for the **Multi-Tenant Enterprise Document Intelligence Platform**.

---

## 1. Production Architecture Overview

The platform uses a practical single-node cloud VPS deployment orchestrated via **Docker Compose**:

```
                                      [ Internet ]
                                           │
                                    Ports 80 / 443
                                           ▼
                 ┌───────────────────────────────────────────────────┐
                 │          Edge Reverse Proxy (Nginx 1.25)          │
                 │  - TLS Termination (Let's Encrypt / ZeroSSL)      │
                 │  - Client Body Limit (50MB for PDF Uploads)       │
                 │  - SSE Unbuffered Streaming (/api/v1/chat/)       │
                 │  - Security Headers (HSTS, NoSniff, SameOrigin)   │
                 └─────────┬───────────────────────────────┬─────────┘
                           │                               │
                / (SPA Static Assets)                 /api/* (REST & SSE)
                           │                               │
                           ▼                               ▼
                 ┌───────────────────┐           ┌───────────────────┐
                 │  React Frontend   │           │  FastAPI Backend  │
                 │  (Nginx Alpine)   │           │  (Python 3.12)    │
                 │  - SPA Fallback   │           │  - Non-root user  │
                 │  - Gzip & Cache   │           │  - 2 Uvicorn wrks │
                 └───────────────────┘           └─────────┬─────────┘
                                                           │
                                   ┌───────────────────────┼───────────────────────┐
                                   │                       │                       │
                                   ▼                       ▼                       ▼
                         ┌───────────────────┐   ┌───────────────────┐   ┌───────────────────┐
                         │   PostgreSQL 16   │   │      Redis 7      │   │   Qdrant v1.12    │
                         │  - docintel_app   │   │  - Auth Protected │   │  - API Key Auth   │
                         │  - True RLS       │   │  - Ingest Queue   │   │  - HNSW Vectors   │
                         │  - Persistent Vol │   │  - Persistent Vol │   │  - Persistent Vol │
                         └───────────────────┘   └─────────┬─────────┘   └───────────────────┘
                                                           │
                                                           ▼
                                                 ┌───────────────────┐
                                                 │   Celery Worker   │
                                                 │  - Async Ingest   │
                                                 │  - Ragas Bench    │
                                                 └───────────────────┘
```

### Hardware Specifications
* **Minimum Host Size**: 2 vCPUs, 4 GB RAM, 40 GB NVMe SSD.
* **Recommended Host Size**: 4 vCPUs, 8 GB RAM, 80 GB NVMe SSD (e.g. Hetzner CPX31, DigitalOcean Droplet, AWS t4g.xlarge / c7g.xlarge).
* **Network Security**: ONLY Port 80 (HTTP) and Port 443 (HTTPS) are exposed publicly. PostgreSQL (5432), Redis (6379), Qdrant (6333/6334), and FastAPI (8000) are strictly internal on the Docker bridge network (`app-network`).

---

## 2. Production Environment Configuration

1. Connect to your production cloud instance via SSH.
2. Clone the repository and navigate into the project directory:
   ```bash
   git clone https://github.com/your-org/doc-intelligence.git /opt/doc_intelligence
   cd /opt/doc_intelligence
   ```
3. Create your production environment file from the template:
   ```bash
   cp .env.production.example .env
   ```
4. Generate strong cryptographic secrets:
   ```bash
   # Generate JWT Secret Key (min 32 bytes)
   openssl rand -hex 32

   # Generate Database & Redis Passwords
   openssl rand -hex 24
   ```
5. Update `.env` with your domain, secrets, and OpenAI API key:
   ```ini
   ENVIRONMENT=production
   DEBUG=False
   DOMAIN_NAME=docs.yourcompany.com
   SECRET_KEY=<generated-hex-32>
   POSTGRES_ADMIN_PASSWORD=<generated-hex-24>
   POSTGRES_APP_PASSWORD=<generated-hex-24>
   REDIS_PASSWORD=<generated-hex-24>
   QDRANT_API_KEY=<generated-hex-24>
   OPENAI_API_KEY=sk-proj-...
   ```

---

## 3. Database Privileges & RLS Setup

The database runs with strict privilege separation:
* **Admin Role (`postgres`)**: Used exclusively by the `migration` container to execute Alembic schema migrations.
* **Application Role (`docintel_app`)**: Non-superuser with `NOSUPERUSER` and `NOBYPASSRLS`. All database interactions by FastAPI and Celery use this role, enforcing PostgreSQL Row-Level Security.

The role initialization script ([scripts/init_prod_db.sql](file:///c:/Users/abhis/OneDrive/Desktop/Placement%20Projects/RAG%20Project/scripts/init_prod_db.sql)) runs automatically upon first container launch:
```sql
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO docintel_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO docintel_app;
```

---

## 4. Launching the Production Stack

1. Build and start the production stack:
   ```bash
   docker compose -f docker-compose.prod.yml build
   docker compose -f docker-compose.prod.yml up -d
   ```
2. Verify container health status:
   ```bash
   docker compose -f docker-compose.prod.yml ps
   ```
   All services (`postgres`, `redis`, `qdrant`, `backend`, `celery_worker`, `frontend`, `nginx`) should report `Up (healthy)`.

---

## 5. SSL / TLS Certificate Automation (Let's Encrypt)

1. Obtain a TLS certificate using Certbot:
   ```bash
   docker run -it --rm --name certbot \
     -v "$(pwd)/data/certbot/certs:/etc/letsencrypt" \
     -v "$(pwd)/data/certbot/www:/var/www/certbot" \
     certbot/certbot certonly --webroot \
     -w /var/www/certbot \
     -d docs.yourcompany.com \
     --email admin@yourcompany.com \
     --agree-tos --no-eff-email
   ```
2. Copy the SSL template into Nginx configuration:
   ```bash
   cp nginx/conf.d/ssl.conf.template nginx/conf.d/ssl.conf
   sed -i 's/${DOMAIN_NAME}/docs.yourcompany.com/g' nginx/conf.d/ssl.conf
   ```
3. Reload Nginx configuration with zero downtime:
   ```bash
   docker exec docintel-prod-proxy nginx -s reload
   ```

---

## 6. Disaster Recovery & Automated Backups

### Automated Daily Backup Schedule (Cron)
Add the following cron job to `/etc/cron.d/docintel-backup` on the host:
```cron
# Run daily database, vector, and storage backup at 02:00 UTC
0 2 * * * root /opt/doc_intelligence/scripts/backup_db.sh >> /var/log/docintel-backup.log 2>&1
```

### Manual Backup Execution
```bash
# Python cross-platform backup:
python scripts/backup_db.py

# Or bash script:
./scripts/backup_db.sh
```

### Restoration Procedure
1. Stop backend workers to prevent concurrent writes:
   ```bash
   docker compose -f docker-compose.prod.yml stop backend celery_worker
   ```
2. Restore database and documents from the target backup archive:
   ```bash
   # Restore PostgreSQL database:
   docker exec -i docintel-prod-postgres psql -U postgres -d doc_intelligence < backups/20261113_XXXX/postgres_backup.sql
   
   # Or using restore script:
   ./scripts/restore_db.sh backups/20261113_XXXX/
   ```
3. Restart application containers:
   ```bash
   docker compose -f docker-compose.prod.yml start backend celery_worker
   ```
4. Verify system health:
   ```bash
   curl -f http://localhost/api/v1/health
   ```

---

## 7. Monitoring & Health Probes

* **Health Endpoint**: `GET /api/v1/health` returns HTTP 200 with JSON latency metrics for PostgreSQL, Redis, and Qdrant.
* **Liveness Probe**: `GET /api/v1/health/live` (HTTP 200 if process is responsive).
* **Readiness Probe**: `GET /api/v1/health/ready` (HTTP 200 only if all backing services are connected).
* **Prometheus Metrics**: `GET /api/v1/metrics` exports request durations, token consumption, and background task failure counters.
