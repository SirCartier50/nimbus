# Nimbus AI — Agentic AWS Management System

Nimbus lets anyone deploy and manage AWS infrastructure using plain English. Three AI agents powered by Amazon Nova via Amazon Bedrock handle the complexity so beginners don't have to.

## What It Does

Type what you want to build — Nimbus plans the architecture, deploys the resources, and monitors everything automatically.

**Example:** "I need a REST API with a database" → Nimbus creates an EC2 instance, S3 bucket, and DynamoDB table, generates deployment configs, and starts monitoring for idle resources.

## Agents

| Agent | Role |
|-------|------|
| **Architect** | Analyzes natural language requests using Amazon Nova and generates optimized AWS infrastructure plans with cost estimates |
| **Executor** | Deploys the approved plan — provisions EC2, S3, DynamoDB, and Lambda resources with proper tagging and configuration |
| **Bodyguard** | Runs continuously in the background, monitoring deployed resources and automatically stopping idle EC2 instances to prevent unnecessary costs |

## Features

- **Chat Interface** — Describe infrastructure in plain English, review plans, confirm deployment
- **Integrated Editor** — View and edit generated config files (setup scripts, docker-compose, teardown scripts, manifests)
- **Terminal** — Run git commands, navigate workspace, link GitHub repos, push deployment configs
- **Dashboard** — Real-time view of all deployed resources, Bodyguard status, and usage metrics
- **File Generation** — Auto-generates setup.sh, teardown.sh, docker-compose.yml, README, and infrastructure manifests after each deployment
- **Free Tier Mode** — Restricts recommendations to AWS free-tier eligible services only
- **GitHub Integration** — Link a repository and push generated infrastructure files directly from the terminal

## Tech Stack

**Backend:** Python, FastAPI, Amazon Bedrock (Nova), boto3
**Frontend:** Next.js 14, TypeScript, Tailwind CSS, Framer Motion
**Auth:** Clerk
**Cloud:** AWS (EC2, S3, DynamoDB, Lambda, CloudWatch)

## Architecture

```
User → Chat UI → Architect Agent (Amazon Nova via Bedrock)
                      ↓
                 Infrastructure Plan
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

## Getting Started

```bash
git clone https://github.com/SirCartier50/nimbus.git
cd nimbus
```

### Backend
```bash
cd backend
pip install -r requirements.txt
cp .env.example .env        # Then fill in your AWS credentials
uvicorn main:app --reload --port 8000
```

### Frontend (in a separate terminal)
```bash
cd frontend
npm install
cp .env.local.example .env.local   # Then fill in your Clerk keys
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) — sign up, connect your AWS account in Settings, and start chatting.

## Category

**Agentic AI** — Multi-agent system using Amazon Nova reasoning capabilities to plan, deploy, and monitor AWS infrastructure.

## Built For

Amazon Nova AI Hackathon 2026
