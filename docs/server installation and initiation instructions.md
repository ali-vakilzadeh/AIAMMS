# CMMS SaaS Server Installation and Initiation Instructions

This document provides step-by-step instructions to install, configure, and run the CMMS (Computerized Maintenance Management System) SaaS server from scratch until it reaches a stable, unattended operational state.

---

## Table of Contents

1. [System Requirements](#1-system-requirements)
2. [Install Prerequisites](#2-install-prerequisites)
3. [Database Setup](#3-database-setup)
4. [Redis Setup](#4-redis-setup)
5. [Application Installation](#5-application-installation)
6. [Configure Secrets and Environment Variables](#6-configure-secrets-and-environment-variables)
7. [Run Database Migrations](#7-run-database-migrations)
8. [Start the Server](#8-start-the-server)
9. [Verify Health and Stability](#9-verify-health-and-stability)
10. [Production Hardening](#10-production-hardening)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. System Requirements

### Minimum Hardware
- **CPU**: 2 cores (4+ recommended for production)
- **RAM**: 4 GB (8+ GB recommended)
- **Storage**: 20 GB SSD (more for file storage)
- **OS**: Linux (Ubuntu 22.04 LTS recommended), macOS, or Windows with WSL2

### Software Dependencies
- **Python**: 3.10 or higher (3.11+ recommended)
- **PostgreSQL**: 14+ with contrib packages (for pgcrypto, citext, vector extensions)
- **Redis**: 6.0+ (for caching, rate limiting, distributed locks)
- **pip**: Python package manager
- **git**: Version control

---

## 2. Install Prerequisites

### 2.1 Install Python

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3.11-dev python3-pip
python3.11 --version
```

**macOS (with Homebrew):**
```bash
brew install python@3.11
python3.11 --version
```

**Windows (WSL2):**
```bash
# Inside WSL2 Ubuntu
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3-pip
```

### 2.2 Install PostgreSQL

**Ubuntu/Debian:**
```bash
sudo apt install -y postgresql postgresql-contrib postgresql-client libpq-dev
sudo systemctl enable postgresql
sudo systemctl start postgresql
sudo systemctl status postgresql
```

**macOS (with Homebrew):**
```bash
brew install postgresql@15
brew services start postgresql@15
```

**Verify PostgreSQL:**
```bash
psql --version
```

### 2.3 Install Redis

**Ubuntu/Debian:**
```bash
sudo apt install -y redis-server
sudo systemctl enable redis-server
sudo systemctl start redis-server
sudo systemctl status redis-server
```

**macOS (with Homebrew):**
```bash
brew install redis
brew services start redis
```

**Verify Redis:**
```bash
redis-cli ping
# Should return: PONG
```

### 2.4 Create Project Directory and Virtual Environment

```bash
cd /workspace
python3.11 -m venv venv
source venv/bin/activate
```

**Verify virtual environment is active:**
```bash
which python
# Should show: /workspace/venv/bin/python
```

### 2.5 Install Python Dependencies

Create a `requirements.txt` file in `/workspace`:

```txt
# Core Framework
fastapi>=0.109.0
uvicorn[standard]>=0.27.0
pydantic>=2.5.0
pydantic-settings>=2.1.0

# Database
sqlalchemy[asyncio]>=2.0.0
asyncpg>=0.29.0
alembic>=1.13.0

# Cache & Messaging
redis>=5.0.0

# Authentication & Security
passlib[argon2]>=1.7.4
PyJWT>=2.8.0
python-jose[cryptography]>=3.3.0

# HTTP Client
httpx>=0.26.0
aiohttp>=3.9.0

# Logging & Monitoring
structlog>=24.1.0

# Testing (optional for production)
pytest>=7.4.0
pytest-asyncio>=0.23.0
```

**Install dependencies:**
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 3. Database Setup

### 3.1 Create Database User and Database

```bash
# Switch to postgres user
sudo -i -u postgres
```

```sql
-- Create database user for CMMS
CREATE USER cmms_user WITH PASSWORD 'your_secure_password_here';

-- Create database
CREATE DATABASE cmms_production OWNER cmms_user;

-- Grant privileges
GRANT ALL PRIVILEGES ON DATABASE cmms_production TO cmms_user;

-- Enable required extensions on the database
\c cmms_production

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS vector;

-- Grant extension usage
GRANT ALL ON ALL TABLES IN SCHEMA public TO cmms_user;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO cmms_user;

-- Exit psql
\q
```

**Exit postgres user:**
```bash
exit
```

### 3.2 Verify Database Connection

```bash
PGPASSWORD='your_secure_password_here' psql -h localhost -U cmms_user -d cmms_production -c "SELECT 1;"
```

---

## 4. Redis Setup

### 4.1 Configure Redis (Optional for Production)

Edit Redis configuration:
```bash
sudo nano /etc/redis/redis.conf
```

**Recommended settings for production:**
```conf
# Bind to localhost only (security)
bind 127.0.0.1

# Set max memory (adjust based on available RAM)
maxmemory 512mb
maxmemory-policy allkeys-lru

# Enable persistence (AOF)
appendonly yes
appendfsync everysec

# Set password (uncomment and set secure password)
# requirepass your_redis_password_here
```

**Restart Redis:**
```bash
sudo systemctl restart redis-server
```

### 4.2 Verify Redis Connection

```bash
redis-cli ping
# Should return: PONG
```

---

## 5. Application Installation

### 5.1 Clone or Copy Application Code

If using git:
```bash
cd /workspace
git clone <repository-url> .
```

Or ensure code is in `/workspace/src/server`

### 5.2 Verify Project Structure

```bash
ls -la /workspace/src/server/
# Should contain: core/, modules/, shared/
```

### 5.3 Add Project to Python Path

Create `.env` file or export PYTHONPATH:
```bash
export PYTHONPATH=/workspace/src:$PYTHONPATH
```

For permanent setup, add to `~/.bashrc` or `~/.profile`:
```bash
echo 'export PYTHONPATH=/workspace/src:$PYTHONPATH' >> ~/.bashrc
source ~/.bashrc
```

---

## 6. Configure Secrets and Environment Variables

The application uses environment variables with the prefix `CMMS_<MODULE>__<KEY>` format.

### 6.1 Create Environment File

Create `/workspace/.env` file:

```bash
# =============================================================================
# DATABASE CONFIGURATION
# =============================================================================
CMMS_DB__URL=postgresql+asyncpg://cmms_user:your_secure_password_here@localhost:5432/cmms_production
CMMS_DB__POOL_SIZE=10
CMMS_DB__MAX_OVERFLOW=20
CMMS_DB__POOL_TIMEOUT=30
CMMS_DB__STATEMENT_TIMEOUT=60000
CMMS_DB__RLS_ENFORCED=true

# =============================================================================
# CACHE CONFIGURATION (Redis)
# =============================================================================
CMMS_CACHE__URL=redis://localhost:6379/0
# If Redis has password: CMMS_CACHE__URL=redis://:your_redis_password@localhost:6379/0

# =============================================================================
# AUTHENTICATION CONFIGURATION
# =============================================================================
CMMS_AUTH__JWT_SECRET=change-this-to-a-very-long-random-secret-key-min-32-chars-in-prod
CMMS_AUTH__ACCESS_TTL_MINUTES=15
CMMS_AUTH__REFRESH_TTL_DAYS=7
CMMS_AUTH__PASSWORD_MIN_LENGTH=10

# =============================================================================
# API CONFIGURATION
# =============================================================================
CMMS_API__CORS_ORIGINS=https://yourdomain.com,https://app.yourdomain.com
CMMS_API__OPENAPI_ENABLED=true
CMMS_API__HOST=0.0.0.0
CMMS_API__PORT=8000

# =============================================================================
# EMAIL CONFIGURATION (Optional - for notifications)
# =============================================================================
# For SMTP provider:
CMMS_EMAIL__PROVIDER=smtp
CMMS_EMAIL__SMTP_HOST=smtp.yourprovider.com
CMMS_EMAIL__SMTP_PORT=587
CMMS_EMAIL__SMTP_USER=noreply@yourdomain.com
CMMS_EMAIL__SMTP_PASSWORD=your_email_password
CMMS_EMAIL__SMTP_TLS=true

# For API provider (e.g., SendGrid):
# CMMS_EMAIL__PROVIDER=api
# CMMS_EMAIL__API_KEY=your_sendgrid_api_key
# CMMS_EMAIL__API_URL=https://api.sendgrid.com/v3/mail/send

# =============================================================================
# STORAGE CONFIGURATION (File uploads)
# =============================================================================
# Local storage:
CMMS_STORAGE__BACKEND=local
CMMS_STORAGE__LOCAL_PATH=/workspace/storage/files
CMMS_STORAGE__MAX_FILE_SIZE_MB=10

# For S3/MinIO:
# CMMS_STORAGE__BACKEND=s3
# CMMS_STORAGE__S3_BUCKET=your-bucket-name
# CMMS_STORAGE__S3_ENDPOINT_URL=https://s3.amazonaws.com
# CMMS_STORAGE__S3_ACCESS_KEY=your_access_key
# CMMS_STORAGE__S3_SECRET_KEY=your_secret_key
# CMMS_STORAGE__S3_REGION=us-east-1

# =============================================================================
# AI CONFIGURATION (Optional - for checklist generation)
# =============================================================================
# CMMS_AI__PROVIDER=openrouter
# CMMS_AI__API_KEY=your_openrouter_api_key
# CMMS_AI__MODEL=meta-llama/llama-3-8b-instruct
# CMMS_AI__RATE_LIMIT_PER_HOUR=100

# =============================================================================
# LOGGING CONFIGURATION
# =============================================================================
LOG_LEVEL=INFO
LOG_FORMAT=json

# =============================================================================
# SERVER PROFILE
# =============================================================================
# Options: api, worker, beat, mcp, all-in-one
SERVER_PROFILE=all-in-one
```

### 6.2 Secure the .env File

```bash
chmod 600 /workspace/.env
chown $(whoami):$(whoami) /workspace/.env
```

### 6.3 Load Environment Variables

**Option A: Export manually**
```bash
set -a
source /workspace/.env
set +a
```

**Option B: Use python-dotenv (recommended)**

Install dotenv:
```bash
pip install python-dotenv
```

Create `/workspace/src/server/main.py`:
```python
"""Main entry point for CMMS server."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(env_path)

from core.boot import BootOrchestrator
from core.supervisor import Supervisor
from core.logger import setup_structured_logging
import asyncio
import uvicorn


def main():
    """Boot and run the CMMS server."""
    
    # Setup logging
    setup_structured_logging()
    
    # Get profile from environment
    profile = os.getenv("SERVER_PROFILE", "all-in-one")
    
    # Boot the application
    orchestrator = BootOrchestrator()
    app = orchestrator.boot(profile=profile)
    
    # Start supervisor for health monitoring
    supervisor = Supervisor(app)
    
    async def run_server():
        # Start supervisor in background
        supervisor_task = asyncio.create_task(supervisor.run(interval_s=30))
        
        # Get API settings
        host = os.getenv("CMMS_API__HOST", "0.0.0.0")
        port = int(os.getenv("CMMS_API__PORT", "8000"))
        
        # Run FastAPI server
        config = uvicorn.Config(
            "modules.api.service:app",
            host=host,
            port=port,
            log_level="info",
        )
        server = uvicorn.Server(config)
        
        try:
            await server.serve()
        finally:
            # Cleanup
            supervisor.running = False
            supervisor_task.cancel()
            orchestrator.shutdown(app)
    
    asyncio.run(run_server())


if __name__ == "__main__":
    main()
```

---

## 7. Run Database Migrations

### 7.1 Initialize Alembic (First Time Only)

```bash
cd /workspace/src/server
alembic init alembic
```

Configure `alembic.ini`:
```ini
script_location = alembic
prepend_sys_path = .
sqlalchemy.url = postgresql+asyncpg://cmms_user:your_secure_password_here@localhost:5432/cmms_production
```

### 7.2 Create Initial Migration

```bash
cd /workspace/src/server
alembic revision --autogenerate -m "Initial schema with all modules"
```

### 7.3 Apply Migrations

**Option A: Via Alembic CLI**
```bash
cd /workspace/src/server
alembic upgrade head
```

**Option B: Programmatically via Application**

The DB module automatically runs migrations during initialization if configured. The `ensure_extensions()` function creates required PostgreSQL extensions (vector, pgcrypto, citext) automatically.

### 7.4 Verify Database Schema

```bash
PGPASSWORD='your_secure_password_here' psql -h localhost -U cmms_user -d cmms_production -c "\dt"
```

Expected tables (partial list):
- organizations
- organization_custom_fields
- user_organization_memberships
- invitations
- subscription_tiers
- payment_states
- users (created by AUTH module)
- assets
- workorders
- tickets
- cycles
- files
- etc.

---

## 8. Start the Server

### 8.1 Development Mode

```bash
cd /workspace
source venv/bin/activate
set -a
source .env
set +a
export PYTHONPATH=/workspace/src:$PYTHONPATH

# Run with auto-reload
uvicorn src.server.modules.api.service:app --host 0.0.0.0 --port 8000 --reload
```

### 8.2 Production Mode

**Using Gunicorn with Uvicorn workers:**

Install gunicorn:
```bash
pip install gunicorn
```

Create `/workspace/gunicorn_conf.py`:
```python
import multiprocessing

bind = "0.0.0.0:8000"
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "uvicorn.workers.UvicornWorker"
threads = 2
timeout = 120
keepalive = 5
accesslog = "/var/log/cmms/access.log"
errorlog = "/var/log/cmms/error.log"
loglevel = "info"

# Graceful shutdown
graceful_timeout = 30
max_requests = 1000
max_requests_jitter = 50
```

**Start with Gunicorn:**
```bash
cd /workspace
source venv/bin/activate
set -a
source .env
set +a
export PYTHONPATH=/workspace/src:$PYTHONPATH

gunicorn -c gunicorn_conf.py src.server.modules.api.service:app
```

### 8.3 Systemd Service (Linux Production)

Create `/etc/systemd/system/cmms-server.service`:

```ini
[Unit]
Description=CMMS SaaS Server
After=network.target postgresql.service redis.service

[Service]
Type=notify
User=cmms
Group=cmms
WorkingDirectory=/workspace
Environment="PATH=/workspace/venv/bin:/usr/local/bin:/usr/bin"
EnvironmentFile=/workspace/.env
ExecStart=/workspace/venv/bin/gunicorn -c /workspace/gunicorn_conf.py src.server.modules.api.service:app
ExecReload=/bin/kill -s HUP $MAINPID
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=cmms-server

# Security hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/workspace/storage /var/log/cmms

[Install]
WantedBy=multi-user.target
```

**Enable and start service:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable cmms-server
sudo systemctl start cmms-server
sudo systemctl status cmms-server
```

---

## 9. Verify Health and Stability

### 9.1 Check Server Logs

```bash
# If using systemd
sudo journalctl -u cmms-server -f

# If using log files
tail -f /var/log/cmms/error.log
```

**Expected startup logs:**
```
INFO: Booting CMMS server with profile: all-in-one
INFO: Loading settings...
INFO: Discovering modules...
INFO: Validating dependency graph...
INFO: Booting module: db
INFO: Creating database engine with pool_size=10
INFO: Extension 'vector' ensured
INFO: Extension 'pgcrypto' ensured
INFO: Extension 'citext' ensured
INFO: Module 'db' started
INFO: Booting module: cache
INFO: Connected to Redis
INFO: Module 'cache' started
INFO: Booting module: auth
INFO: Module 'auth' started
INFO: Booting module: api
INFO: Starting API server on 0.0.0.0:8000
INFO: All 12 modules booted successfully
INFO: Starting supervisor with 30s interval
```

### 9.2 Health Check Endpoints

**Check overall health:**
```bash
curl http://localhost:8000/api/v1/health
```

Expected response:
```json
{
  "status": "OK",
  "timestamp": "2024-01-15T10:30:00Z",
  "modules": {
    "db": {"status": "OK", "checks": [{"name": "connectivity", "status": "OK"}]},
    "cache": {"status": "OK"},
    "auth": {"status": "OK"},
    "api": {"status": "OK"}
  }
}
```

**Check individual module health:**
```bash
curl http://localhost:8000/api/v1/health/db
curl http://localhost:8000/api/v1/health/cache
```

### 9.3 Test API Connectivity

```bash
# Get OpenAPI schema
curl http://localhost:8000/api/v1/openapi.json | jq '.info'

# Test authentication endpoint (should return 401 without token)
curl -I http://localhost:8000/api/v1/auth/me
```

### 9.4 Monitor Process Stability

```bash
# Check process is running
ps aux | grep gunicorn

# Check memory usage
top -p $(pgrep -f gunicorn)

# Check open connections
netstat -tlnp | grep 8000
```

### 9.5 Database Connection Pool Check

```bash
PGPASSWORD='your_secure_password_here' psql -h localhost -U cmms_user -d cmms_production -c "SELECT count(*) FROM pg_stat_activity WHERE datname = 'cmms_production';"
```

---

## 10. Production Hardening

### 10.1 SSL/TLS Configuration

**Using Nginx as reverse proxy:**

Install Nginx:
```bash
sudo apt install -y nginx
```

Create `/etc/nginx/sites-available/cmms`:
```nginx
server {
    listen 80;
    server_name yourdomain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
        proxy_read_timeout 120s;
        proxy_connect_timeout 60s;
    }

    location /ws {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "Upgrade";
        proxy_set_header Host $host;
    }
}
```

**Enable site and get SSL certificate:**
```bash
sudo ln -s /etc/nginx/sites-available/cmms /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx

# Install certbot for Let's Encrypt
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.com
```

### 10.2 Firewall Configuration

```bash
# Allow only necessary ports
sudo ufw default deny incoming
sudo ufw allow ssh
sudo ufw allow http
sudo ufw allow https
sudo ufw enable
```

### 10.3 Database Backup Strategy

Create `/workspace/scripts/backup_db.sh`:
```bash
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/workspace/backups/db"
mkdir -p $BACKUP_DIR

PGPASSWORD='your_secure_password_here' pg_dump -h localhost -U cmms_user cmms_production > $BACKUP_DIR/cmms_$DATE.sql.gz

# Keep only last 7 days
find $BACKUP_DIR -name "*.sql.gz" -mtime +7 -delete
```

Make executable and add to crontab:
```bash
chmod +x /workspace/scripts/backup_db.sh
crontab -e
# Add: 0 2 * * * /workspace/scripts/backup_db.sh
```

### 10.4 Log Rotation

Create `/etc/logrotate.d/cmms`:
```
/var/log/cmms/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 0640 cmms cmms
    postrotate
        systemctl reload cmms-server
    endscript
}
```

### 10.5 Monitoring Setup

**Install Prometheus Node Exporter:**
```bash
sudo apt install -y prometheus-node-exporter
sudo systemctl enable prometheus-node-exporter
sudo systemctl start prometheus-node-exporter
```

**Configure application metrics endpoint** (add to API module):
```python
@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    # Export application metrics
    pass
```

---

## 11. Troubleshooting

### Common Issues and Solutions

#### Issue: Database connection fails
**Symptoms:**
```
ERROR: Could not connect to database
```

**Solutions:**
1. Verify PostgreSQL is running: `sudo systemctl status postgresql`
2. Check credentials in `.env` file
3. Verify database exists: `psql -l | grep cmms`
4. Check pg_hba.conf allows connections
5. Ensure extensions are installed: `\dx` in psql

#### Issue: Redis connection fails
**Symptoms:**
```
ERROR: Redis connection refused
```

**Solutions:**
1. Verify Redis is running: `sudo systemctl status redis-server`
2. Check Redis URL in `.env`
3. Test connection: `redis-cli ping`
4. Check firewall rules

#### Issue: Module boot fails
**Symptoms:**
```
ERROR: Module 'auth' failed to boot: JWT_SECRET not configured
```

**Solutions:**
1. Check `.env` file is loaded
2. Verify environment variable names match exactly (case-sensitive)
3. Ensure all required secrets are set

#### Issue: Port already in use
**Symptoms:**
```
ERROR: Address already in use: 0.0.0.0:8000
```

**Solutions:**
```bash
# Find process using port 8000
sudo lsof -i :8000

# Kill the process
sudo kill -9 <PID>

# Or change port in .env
CMMS_API__PORT=8001
```

#### Issue: Import errors
**Symptoms:**
```
ModuleNotFoundError: No module named 'core'
```

**Solutions:**
1. Verify PYTHONPATH: `echo $PYTHONPATH`
2. Should include: `/workspace/src`
3. Activate virtual environment: `source venv/bin/activate`
4. Reinstall dependencies: `pip install -r requirements.txt`

#### Issue: Database migrations fail
**Symptoms:**
```
ERROR: relation "users" does not exist
```

**Solutions:**
1. Run migrations: `alembic upgrade head`
2. Check migration files exist in `alembic/versions/`
3. Verify database user has CREATE privileges

### Getting Help

1. **Check logs:** `sudo journalctl -u cmms-server -n 100`
2. **Health endpoints:** `curl http://localhost:8000/api/v1/health`
3. **Database logs:** `sudo tail -f /var/log/postgresql/postgresql-*.log`
4. **Redis logs:** `sudo tail -f /var/log/redis/redis-server.log`

---

## Post-Installation Checklist

- [ ] PostgreSQL installed and running
- [ ] Redis installed and running
- [ ] Python virtual environment created
- [ ] All dependencies installed
- [ ] Database user and database created
- [ ] PostgreSQL extensions enabled (pgcrypto, citext, vector)
- [ ] `.env` file configured with all secrets
- [ ] Database migrations applied successfully
- [ ] Server starts without errors
- [ ] Health endpoint returns OK status
- [ ] SSL/TLS configured (production)
- [ ] Firewall rules configured
- [ ] Backup strategy implemented
- [ ] Monitoring configured
- [ ] Log rotation configured

---

## Quick Start Commands Summary

```bash
# 1. Install prerequisites
sudo apt update && sudo apt install -y python3.11 python3.11-venv postgresql redis-server

# 2. Setup database
sudo -i -u postgres
psql -c "CREATE USER cmms_user WITH PASSWORD 'secure_password';"
psql -c "CREATE DATABASE cmms_production OWNER cmms_user;"
psql -d cmms_production -c "CREATE EXTENSION IF NOT EXISTS pgcrypto; CREATE EXTENSION IF NOT EXISTS citext; CREATE EXTENSION IF NOT EXISTS vector;"
exit

# 3. Setup application
cd /workspace
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
nano .env  # Edit with your secrets

# 5. Run migrations
cd src/server
alembic upgrade head

# 6. Start server
cd /workspace
source venv/bin/activate
set -a && source .env && set +a
export PYTHONPATH=/workspace/src:$PYTHONPATH
uvicorn src.server.modules.api.service:app --host 0.0.0.0 --port 8000

# 7. Verify
curl http://localhost:8000/api/v1/health
```

---

## Document Information

- **Version:** 1.0
- **Last Updated:** 2024
- **Applies to:** CMMS SaaS Server v1.0
- **Author:** Development Team
