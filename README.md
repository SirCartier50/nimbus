# Nimbus AI — Agentic AWS Management

Nimbus lets anyone deploy and manage AWS infrastructure using plain English. Describe what you want to build; three AI agents handle the planning, deployment, and cost monitoring automatically.

**Example:** "I need a REST API with a database" → Nimbus designs the architecture, deploys EC2 + S3 + DynamoDB, generates your config files, and starts monitoring for idle resources.

## Agents

| Agent | Role |
|-------|------|
| **Architect** | Turns natural language requests into AWS infrastructure plans with cost estimates |
| **Executor** | Deploys the approved plan — provisions and tags EC2, S3, DynamoDB, and Lambda |
| **Bodyguard** | Runs in the background, monitoring resources and auto-stopping idle EC2 instances to prevent surprise bills |

## Features

- **Chat Interface** — Describe infrastructure in plain English, review the plan, confirm deployment
- **Activity Panel** — Live agent reasoning stream so you can see exactly what Nimbus is doing and why
- **Dashboard** — Real-time view of all deployed resources, Bodyguard status, and usage metrics
- **File Generation** — Auto-generates setup.sh, teardown.sh, docker-compose.yml, and infrastructure manifests after each deployment
- **Free Tier Mode** — Restricts recommendations to AWS free-tier eligible services only
- **Per-session Region** — Choose an AWS region per conversation, not globally

## Tech Stack

**Backend:** Python 3.11, FastAPI, Amazon Bedrock (Nova), boto3, SQLAlchemy 2.0 (async), Alembic  
**Frontend:** Next.js 16, TypeScript, Tailwind CSS, Framer Motion  
**Auth:** Clerk (JWT / RS256)  
**Database:** PostgreSQL via Supabase  
**Cloud:** AWS (EC2, S3, DynamoDB, Lambda, CloudWatch)

## Architecture

```
User → Chat UI → Architect Agent (Amazon Nova via Bedrock)
                      ↓
                Infrastructure Plan
                      ↓
               User approves/rejects
                      ↓
               Executor Agent (boto3)
                      ↓
             AWS Resources Deployed
                      ↓
             Bodyguard Agent (background monitoring)
```

## Prerequisites

- Python 3.10+
- Node.js 18+
- An AWS account with access keys (IAM user with `PowerUserAccess`)
- A [Clerk](https://clerk.com) account (free tier works)
- A [Supabase](https://supabase.com) project (free tier works) — copy the connection string from Project Settings → Database

## Getting Started

```bash
git clone https://github.com/SirCartier50/nimbus.git
cd nimbus
```

### Option A — Docker (recommended)

```bash
cp .env.example .env          # fill in all values
docker compose up --build
```

Open [http://localhost:3000](http://localhost:3000).

### Option B — Local dev

**Backend**
```bash
cd backend
pip install -r requirements.txt
cp .env.example .env          # fill in AWS, Clerk, and Supabase values
uvicorn main:app --reload --port 8000
```

**Frontend** (separate terminal)
```bash
cd frontend
npm install
cp .env.local.example .env.local   # fill in Clerk publishable key and backend URL
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) — sign up, add your AWS credentials in Settings, and start chatting.

## Environment Variables

See `.env.example` and `backend/.env.example` for the full list. The required ones:

| Variable | Where to get it |
|----------|----------------|
| `CLERK_ISSUER` | Clerk Dashboard → API Keys → Issuer URL |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | Clerk Dashboard → API Keys |
| `DATABASE_URL` | Supabase → Project Settings → Database → Connection string (swap `postgresql://` → `postgresql+asyncpg://`) |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | AWS IAM → your user → Security credentials |
| `AWS_REGION` | Your preferred default region (e.g. `us-east-1`) |
