#!/bin/bash
# Bring up the observability stack on its own Amazon Linux 2023 instance.
#
# deploy/observability.cfn.yaml's UserData clones the repository and runs this;
# re-running it is how a change to observability/ reaches the instance:
#
#   cd /opt/loopboard/repo && sudo git pull --ff-only
#   sudo /opt/loopboard/app/deploy/observability-bootstrap.sh
#
# Settings come from /etc/loopboard-observability/deploy.env, written by
# UserData: GRAFANA_ROOT_URL and GRAFANA_PASSWORD_PARAMETER.
set -euo pipefail

ENV_FILE=/etc/loopboard-observability/deploy.env
APP_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
OBS_DIR=$APP_DIR/observability
COMPOSE=(docker compose -f "$OBS_DIR/docker-compose.yaml" -f "$OBS_DIR/docker-compose.deploy.yaml")

# shellcheck source=/dev/null
[[ -f $ENV_FILE ]] && source "$ENV_FILE"
GRAFANA_ROOT_URL=${GRAFANA_ROOT_URL:-}
GRAFANA_PASSWORD_PARAMETER=${GRAFANA_PASSWORD_PARAMETER:-}

log() { printf '\n=== %s\n' "$*"; }

# ------------------------------------------------------------------ packages --
if ! command -v docker >/dev/null; then
	log "installing docker"
	dnf install -y docker
fi
systemctl enable --now docker

# Pinned for the same reason as in bootstrap.sh: the same script should build
# the same box next month.
COMPOSE_VERSION=v2.32.4
PLUGIN=/usr/local/lib/docker/cli-plugins/docker-compose
if [[ ! -x $PLUGIN ]]; then
	log "installing docker compose $COMPOSE_VERSION"
	install -d "$(dirname "$PLUGIN")"
	curl -fsSL -o "$PLUGIN" \
		"https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-$(uname -m)"
	chmod +x "$PLUGIN"
fi

# ---------------------------------------------------------------------- swap --
# Five JVM-free but hungry processes in 2 GiB; swap turns a spike into a slow
# query rather than an OOM-killed Loki.
if [[ ! -f /swapfile ]]; then
	log "adding 2 GiB of swap"
	dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
	chmod 600 /swapfile
	mkswap /swapfile >/dev/null
	swapon /swapfile
	grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >>/etc/fstab
fi

# ------------------------------------------------------------------- secrets --
# Generated once and kept: Grafana applies the admin password only when it
# creates its database, so a new one on a re-run would match nothing. Also
# copied to SSM as a SecureString so it can be read without a shell here.
umask 077
install -d -m 700 /etc/loopboard-observability
SECRET_FILE=/etc/loopboard-observability/grafana_admin_password
if [[ ! -s $SECRET_FILE ]]; then
	log "generating the Grafana admin password"
	openssl rand -base64 18 | tr -d '/+=' >"$SECRET_FILE"
fi
GRAFANA_ADMIN_PASSWORD=$(cat "$SECRET_FILE")

if [[ -n $GRAFANA_PASSWORD_PARAMETER ]]; then
	token=$(curl -fsS -X PUT -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' \
		http://169.254.169.254/latest/api/token)
	region=$(curl -fsS -H "X-aws-ec2-metadata-token: $token" \
		http://169.254.169.254/latest/meta-data/placement/region)
	log "storing the Grafana admin password in SSM $GRAFANA_PASSWORD_PARAMETER"
	aws ssm put-parameter --region "$region" --name "$GRAFANA_PASSWORD_PARAMETER" \
		--type SecureString --overwrite --value "$GRAFANA_ADMIN_PASSWORD" >/dev/null
fi

cat >"$OBS_DIR/.env" <<ENV
# Written by observability-bootstrap.sh.
GRAFANA_ADMIN_PASSWORD=$GRAFANA_ADMIN_PASSWORD
GRAFANA_ROOT_URL=$GRAFANA_ROOT_URL
ENV
chmod 600 "$OBS_DIR/.env"

# ----------------------------------------------------------------------- up ---
log "starting the observability stack"
"${COMPOSE[@]}" --project-directory "$OBS_DIR" up -d --wait --wait-timeout 300

log "running containers"
"${COMPOSE[@]}" --project-directory "$OBS_DIR" ps
