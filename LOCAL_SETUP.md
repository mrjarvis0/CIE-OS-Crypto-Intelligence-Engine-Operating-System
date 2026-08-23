# CIE-OS: Cloud se Local Development pe Switch Karna

Agar future mein cloud band karke apne laptop pe locally chalana ho, ye guide follow karo.

---

## Quick Summary

Cloud deployment mein Docker use hota hai (`docker-compose.yml`), par locally chalane ke liye Docker ki zaroorat NAHI hai. Direct Python se chala sakte ho.

---

## Step 1: Prerequisites Install Karo

```bash
# Python 3.11+ hona chahiye
python --version

# Virtual environment banao
python -m venv .venv

# Activate karo
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

# A01 dependencies install karo
cd agents/A01_Blockchain_Intelligence
pip install "."
# Ya agar PostgreSQL/Redis bhi chahiye:
# pip install ".[all]"

# A02 dependencies install karo
cd ../..
pip install pydantic "pydantic-settings>=2.3" aiosqlite
```

## Step 2: Environment Setup

```bash
# Root .env file banao (ya copy karo)
cp .env.production.example .env

# .env mein ye change karo:
#   APP_ENV=development    (production ki jagah)
#   DEBUG=true             (false ki jagah)
```

## Step 3: A01 Blockchain Intelligence Chalao

### Doctor Check (system validation)
```bash
cd agents/A01_Blockchain_Intelligence
python -m cli.main doctor
```

### REST API Start Karo (local development mein 127.0.0.1 pe)
```bash
python -m cli.main serve
# API available at: http://127.0.0.1:8801
```

> **NOTE:** Cloud pe `--host 0.0.0.0` use hota hai taaki bahar se accessible ho.
> Locally `--host` mat do — default `127.0.0.1` safe hai.

### Blockchain Data Ingest Karo
```bash
python -m cli.main ingest --chain ethereum --blocks 50
```

### Chains aur Detectors Dekho
```bash
python -m cli.main chains
python -m cli.main detectors
```

## Step 4: A02 News Intelligence Chalao

```bash
# Project root se run karo (agents/ ke andar se nahi)
cd F:\CIE-OS

# Doctor check
python -m agents.A02_News_Intelligence.cli doctor

# News scan karo
python -m agents.A02_News_Intelligence.cli scan

# Narratives dekho
python -m agents.A02_News_Intelligence.cli narratives

# Market impact check
python -m agents.A02_News_Intelligence.cli impact
```

## Step 5: Scheduled Runs (Optional)

Cloud pe systemd timers automatic chalate hain. Locally ye options hain:

### Option A: Manual (jab chahiye tab chalao)
```bash
python -m cli.main ingest --chain ethereum --blocks 50
python -m agents.A02_News_Intelligence.cli scan
```

### Option B: Windows Task Scheduler
A01 mein already ek script hai:
```powershell
# 10-minute interval pe ingest chalata hai
agents\A01_Blockchain_Intelligence\scripts\install-task.ps1
```

### Option C: Loop script banao
```bash
# Simple loop (Ctrl+C se band karo)
while true; do
    python -m cli.main ingest --chain ethereum --blocks 50
    sleep 900  # 15 minutes
done
```

---

## Cloud vs Local: Key Differences

| Setting | Cloud (Docker) | Local (Direct Python) |
|---------|---------------|----------------------|
| APP_ENV | `production` | `development` |
| DEBUG | `false` | `true` |
| REST API host | `0.0.0.0` (public) | `127.0.0.1` (loopback) |
| Database | Docker volume | `./data/database/a01.db` |
| Scheduling | systemd timers | Manual / Task Scheduler |
| Dependencies | Dockerfile installs | `pip install` in venv |

---

## Docker se bhi Local Test Kar Sakte Ho

Agar Docker installed hai laptop pe:

```bash
# Sirf API chalao
docker compose up a01-api

# Ingest ek baar chalao
docker compose run --rm --profile scheduled a01-ingest

# News scan ek baar chalao
docker compose run --rm --profile scheduled a02-scan

# Sab band karo
docker compose down
```

---

## Troubleshooting

### "ModuleNotFoundError" aaye to:
```bash
# PYTHONPATH set karo
# Windows:
set PYTHONPATH=F:\CIE-OS
# Linux/Mac:
export PYTHONPATH=/path/to/CIE-OS
```

### SQLite database fresh start chahiye:
```bash
# A01 database delete karo
del agents\A01_Blockchain_Intelligence\data\database\a01.db

# A02 database delete karo
del agents\A02_News_Intelligence\data\processed\a02.db
```

### API keys nahi hain:
Koi problem nahi — dono agents bina keys ke chalte hain (degraded mode).
A01 ke paas 13 free blockchain endpoints hain. A02 RSS feeds se news le leta hai.
