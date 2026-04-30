#!/bin/bash
set -euo pipefail
trap 'echo "RepoSwarm cloud-init failed on line $LINENO (pid $$)" >&2' ERR

DOMAIN="${domain_name}"
EMAIL="${letsencrypt_email}"
REPOSWARM_API_TOKEN=$(cat <<'REPOSWARM_API_TOKEN_END'
${reposwarm_api_token}
REPOSWARM_API_TOKEN_END
)
ANTHROPIC_API_KEY=$(cat <<'ANTHROPIC_API_KEY_END'
${anthropic_api_key}
ANTHROPIC_API_KEY_END
)
OPENROUTER_API_KEY=$(cat <<'OPENROUTER_API_KEY_END'
${openrouter_api_key}
OPENROUTER_API_KEY_END
)
GITHUB_TOKEN=$(cat <<'GITHUB_TOKEN_END'
${github_token}
GITHUB_TOKEN_END
)
LLM_PROVIDER="${llm_provider}"

if [ -z "$$REPOSWARM_API_TOKEN" ] || [ "$$(printf '%s' "$$REPOSWARM_API_TOKEN" | tr -d '[:space:]')" = "" ]; then
  echo "ERROR: REPOSWARM_API_TOKEN is empty or whitespace-only" >&2
  exit 1
fi
case "$$REPOSWARM_API_TOKEN" in *"
"* | *"
"*) echo "ERROR: REPOSWARM_API_TOKEN contains newline/CRLF" >&2; exit 1;; esac

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get upgrade -y
apt-get install -y curl nginx certbot python3-certbot-nginx ufw ca-certificates docker.io

systemctl enable --now docker

mkdir -p /opt/reposwarm

cat > /opt/reposwarm/docker-compose.yml <<'COMPOSE'
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: temporal
      POSTGRES_PASSWORD: temporal
      POSTGRES_DB: temporal
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U temporal"]
      interval: 5s
      timeout: 3s
      retries: 10

  temporal:
    image: temporalio/auto-setup:1.26.2
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      - DB=postgres12
      - DB_PORT=5432
      - POSTGRES_USER=temporal
      - POSTGRES_PWD=temporal
      - POSTGRES_SEEDS=postgres
      - TEMPORAL_ADDRESS=temporal:7233
      - TEMPORAL_CLI_ADDRESS=temporal:7233
    ports:
      - "127.0.0.1:7233:7233"
    healthcheck:
      test: ["CMD", "tctl", "cluster", "health"]
      interval: 10s
      timeout: 5s
      retries: 30
      start_period: 60s

  dynamodb:
    image: amazon/dynamodb-local:latest
    command: "-jar DynamoDBLocal.jar -inMemory"
    environment:
      AWS_ACCESS_KEY_ID: dummy
      AWS_SECRET_ACCESS_KEY: dummy
      AWS_REGION: us-east-1
    ports:
      - "127.0.0.1:8000:8000"

  api:
    image: ghcr.io/reposwarm/api:latest
    depends_on:
      temporal:
        condition: service_healthy
      dynamodb:
        condition: service_started
    environment:
      - TEMPORAL_ADDRESS=temporal:7233
      - DYNAMODB_ENDPOINT=http://dynamodb:8000
      - AWS_ACCESS_KEY_ID=dummy
      - AWS_SECRET_ACCESS_KEY=dummy
      - AWS_REGION=us-east-1
      - API_TOKEN=$${REPOSWARM_API_TOKEN}
      - PORT=3000
    ports:
      - "127.0.0.1:3000:3000"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/v1/health"]
      interval: 5s
      timeout: 3s
      retries: 10

  litellm:
    image: ghcr.io/berriai/litellm:main-latest
    command: ["--model", "openrouter/anthropic/claude-sonnet-4-20250514", "--port", "4000"]
    environment:
      - OPENROUTER_API_KEY=$${OPENROUTER_API_KEY}
    ports:
      - "127.0.0.1:4000:4000"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:4000/health"]
      interval: 10s
      timeout: 3s
      retries: 10

  worker:
    image: ghcr.io/reposwarm/worker:latest
    depends_on:
      temporal:
        condition: service_healthy
      api:
        condition: service_healthy
      litellm:
        condition: service_healthy
    environment:
      - TEMPORAL_ADDRESS=temporal:7233
      - API_URL=http://api:3000/v1
      - API_TOKEN=$${REPOSWARM_API_TOKEN}
      - DYNAMODB_ENDPOINT=http://dynamodb:8000
      - AWS_ACCESS_KEY_ID=dummy
      - AWS_SECRET_ACCESS_KEY=dummy
      - AWS_REGION=us-east-1
      - CLAUDE_PROVIDER=litellm
      - CLAUDE_CODE_USE_BEDROCK=0
      - LITELLM_URL=http://litellm:4000
      - ANTHROPIC_API_KEY=$${ANTHROPIC_API_KEY}
      - ANTHROPIC_MODEL=claude-sonnet-4-20250514
      - GITHUB_TOKEN=$${GITHUB_TOKEN}
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 10s
      timeout: 3s
      retries: 10

  ui:
    image: ghcr.io/reposwarm/ui:latest
    depends_on:
      api:
        condition: service_healthy
    environment:
      - API_URL=http://api:3000/v1
      - PORT=3001
    ports:
      - "127.0.0.1:3001:3001"

volumes:
  postgres_data:
COMPOSE

REPOSWARM_API_TOKEN="$$REPOSWARM_API_TOKEN" \
ANTHROPIC_API_KEY="$$ANTHROPIC_API_KEY" \
OPENROUTER_API_KEY="$$OPENROUTER_API_KEY" \
GITHUB_TOKEN="$$GITHUB_TOKEN" \
docker compose -f /opt/reposwarm/docker-compose.yml up -d

unset REPOSWARM_API_TOKEN ANTHROPIC_API_KEY OPENROUTER_API_KEY GITHUB_TOKEN

cat > /etc/nginx/sites-available/reposwarm <<NGINX
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN;

    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    location /v1/ {
        proxy_pass http://127.0.0.1:3000/v1/;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 300s;
    }

    location / {
        proxy_pass http://127.0.0.1:3001;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 300s;
    }
}
NGINX

ln -sf /etc/nginx/sites-available/reposwarm /etc/nginx/sites-enabled/reposwarm
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

if [ -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]; then
  echo "Reusing existing Let's Encrypt cert"
  certbot --nginx -d "$$DOMAIN" --non-interactive --agree-tos --email "$$EMAIL" --redirect --keep-until-expiring
else
  echo "No existing cert - requesting from Let's Encrypt"
  certbot --nginx -d "$$DOMAIN" --non-interactive --agree-tos --email "$$EMAIL" --redirect
fi
( crontab -l 2>/dev/null || true; echo "17 3 * * * /usr/bin/certbot renew --quiet" ) | crontab -

ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

if [ -f /var/lib/cloud/instance/user-data.txt ]; then
  shred -u /var/lib/cloud/instance/user-data.txt 2>/dev/null || rm -f /var/lib/cloud/instance/user-data.txt
fi

echo "RepoSwarm cloud-init bootstrap complete (domain: $DOMAIN)."
