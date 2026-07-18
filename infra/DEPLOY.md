# Nimbus production deploy (PROD-4)

Backend: one free-tier EC2 instance running docker compose (Caddy → API,
Bodyguard worker, Redis). Frontend: Vercel free tier. Database stays on
Supabase. CI (`.github/workflows/ci.yml`) gates every deploy;
`.github/workflows/deploy.yml` ships main automatically once CI is green.

## Honest availability statement

`restart: unless-stopped` + EC2 auto-recovery restarts anything that *crashes*
(app process, container, even the hypervisor host). What this setup does NOT
survive is the instance itself being terminated or an AZ outage — that
requires paid multi-node (ECS/EKS + ALB), and Kubernetes on a single node
would not change that either. Same Docker images migrate there unchanged when
traffic justifies it.

## One-time EC2 setup (user actions)

1. **Launch instance** — EC2 console → Launch: Ubuntu 24.04 LTS, `t2.micro`
   or `t3.micro` (free tier), 30 GB gp3 root volume (free tier includes 30 GB).
   Security group: allow inbound 22 (your IP only), 80, 443. Allocate + attach
   an **Elastic IP** (free while attached to a running instance).
2. **DNS** — point `api.<yourdomain>` (an A record) at the Elastic IP. Caddy
   gets its Let's Encrypt cert from this — it must resolve before first boot.
3. **Install Docker + swap** (1 GB RAM needs swap headroom for image builds):
   ```bash
   sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 git
   sudo usermod -aG docker ubuntu && newgrp docker
   sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
   sudo mkswap /swapfile && sudo swapon /swapfile
   echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
   ```
4. **Clone + secrets**:
   ```bash
   sudo mkdir -p /opt/nimbus && sudo chown ubuntu:ubuntu /opt/nimbus
   git clone https://github.com/SirCartier50/nimbus.git /opt/nimbus
   cd /opt/nimbus
   # create backend/.env from backend/.env.example with the real values
   echo 'DOMAIN=api.<yourdomain>' > .env   # read by docker-compose.prod.yml
   ```
5. **First boot**: `docker compose -f docker-compose.prod.yml up -d --build`
   then check `curl https://api.<yourdomain>/health`.
6. **EC2 auto-recovery** — EC2 console → the instance → Actions → Monitoring →
   Manage CloudWatch alarms → create the default `StatusCheckFailed_System`
   alarm with the *Recover* action. Free, and brings the box back on
   hypervisor-level failures.
7. **Uptime monitor** — point a free checker (UptimeRobot etc.) at
   `https://api.<yourdomain>/health/ready` so a dead box pages you instead of
   a user.

## GitHub secrets for auto-deploy

Repo → Settings → Secrets and variables → Actions:

| Secret | Value |
| --- | --- |
| `DEPLOY_HOST` | the Elastic IP or public DNS |
| `DEPLOY_USER` | `ubuntu` |
| `DEPLOY_SSH_KEY` | private key (generate a dedicated pair: `ssh-keygen -t ed25519 -f nimbus-deploy`; append `nimbus-deploy.pub` to `~/.ssh/authorized_keys` on the box) |

Until these exist, the Deploy workflow fails at the SSH step — CI is unaffected.

## Vercel (frontend)

1. vercel.com → Add New Project → import the GitHub repo, set **Root
   Directory = `frontend`** (framework auto-detects Next.js).
2. Environment variables: `NEXT_PUBLIC_API_URL=https://api.<yourdomain>`,
   `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`, and the four
   `NEXT_PUBLIC_CLERK_*_URL` values from `frontend/.env.local.example`.
3. After the first deploy: add the Vercel domain to `ALLOWED_ORIGINS` in
   `backend/.env` on the EC2 box (comma-separated) and restart the backend
   service; add the domain in Clerk Dashboard → Domains as well.

## Ops crib sheet

```bash
cd /opt/nimbus
docker compose -f docker-compose.prod.yml ps                    # what's running
docker compose -f docker-compose.prod.yml logs -f backend       # JSON logs
docker compose -f docker-compose.prod.yml logs -f worker        # patrol logs
docker compose -f docker-compose.prod.yml up -d --build         # manual deploy
docker compose -f docker-compose.prod.yml exec backend alembic current
curl -s localhost  # 403/redirect — Caddy owns 80/443; API only via the domain
```

`/metrics` is blocked at Caddy (unauthenticated Prometheus data); scrape it
from the box: `docker compose -f docker-compose.prod.yml exec caddy wget -qO- http://backend:8000/metrics`.
