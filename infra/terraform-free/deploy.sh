#!/usr/bin/env bash
# Copy the app to the free-tier EC2 server and (re)start it. Run from the repo root (Git Bash / WSL / Linux / macOS).
# Usage: infra/terraform-free/deploy.sh /path/to/key.pem
set -euo pipefail

KEY="${1:?usage: deploy.sh /path/to/key.pem}"
IP="$(terraform -chdir=infra/terraform-free output -raw public_ip)"
URL="$(terraform -chdir=infra/terraform-free output -raw site_url)"
SSH=(ssh -i "$KEY" -o StrictHostKeyChecking=accept-new "ec2-user@$IP")

echo ">> Checking SSH access to $IP"
if ! "${SSH[@]}" -o ConnectTimeout=15 true 2>/tmp/deploy-ssh.err; then
  echo "Cannot SSH to $IP:"; sed 's/^/   /' /tmp/deploy-ssh.err
  echo "Most likely your public IP changed. Port 22 only allows ssh_cidr from terraform.tfvars."
  echo "Your current IP: $(curl -s -m 10 https://checkip.amazonaws.com || echo unknown)  -> set ssh_cidr = \"<ip>/32\" and run:"
  echo "   terraform -chdir=infra/terraform-free apply -target=aws_security_group.this"
  exit 1
fi

echo ">> Waiting for first-boot setup on $IP"
for _ in $(seq 1 60); do "${SSH[@]}" 'test -f /var/lib/cloud/control-tower-ready' 2>/dev/null && break; sleep 10; done
"${SSH[@]}" 'test -f /var/lib/cloud/control-tower-ready' || { echo "Server not ready; see /var/log/control-tower-bootstrap.log on it"; exit 1; }

echo ">> Uploading code (the server's .env files are kept)"
tar czf - --exclude=node_modules --exclude=dist --exclude=.venv --exclude=__pycache__ --exclude=.git \
    --exclude='.env' --exclude=storage --exclude=.test_storage --exclude=.terraform --exclude='*.tfstate*' \
    --exclude='backend/tests/fixtures' backend frontend docker-compose.free.yml Caddyfile \
  | "${SSH[@]}" 'cd /opt/control-tower && tar xzf -'

echo ">> Building and starting (first build takes several minutes on a micro instance)"
"${SSH[@]}" 'cd /opt/control-tower && docker compose -f docker-compose.free.yml up -d --build && docker image prune -f >/dev/null'
echo "Done: $URL"
