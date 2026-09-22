#!/bin/bash
# Bring the deployed stack up on a fresh Amazon Linux 2023 instance.
#
# The CloudFormation template's UserData installs git, clones the repository to
# /opt/loopboard/app and runs this. Running it again is the redeploy:
#
#   cd /opt/loopboard/app && sudo git pull && sudo deploy/bootstrap.sh
#
# Everything it needs comes from /etc/loopboard/deploy.env, which UserData
# writes from the stack's parameters. Nothing here reads the instance metadata
# or calls AWS, so it also runs on any other Debian/RHEL-ish box with the same
# file in place.
set -euo pipefail

ENV_FILE=/etc/loopboard/deploy.env
DEPLOY_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
COMPOSE=(docker compose -f "$DEPLOY_DIR/docker-compose.prod.yaml")

# DOMAIN_NAME, LETSENCRYPT_EMAIL and SEED_DEMO_DATA, all possibly empty.
# shellcheck source=/dev/null
[[ -f $ENV_FILE ]] && source "$ENV_FILE"
DOMAIN_NAME=${DOMAIN_NAME:-}
LETSENCRYPT_EMAIL=${LETSENCRYPT_EMAIL:-}
SEED_DEMO_DATA=${SEED_DEMO_DATA:-false}

log() { printf '\n=== %s\n' "$*"; }

# ------------------------------------------------------------------ packages --
if ! command -v docker >/dev/null; then
	log "installing docker"
	dnf install -y docker
fi
systemctl enable --now docker

# The compose plugin is not in the Amazon Linux repositories, so it comes from
# the project's own release. Pinned: an unpinned `latest` makes the box that
# was built today and the box built next month two different deployments.
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
# `npm ci` plus a Vite build peaks above what 2 GiB of RAM has spare once
# Postgres and the Docker daemon have taken theirs; the build is then killed by
# the OOM killer, which reads as an inscrutable exit 137 from docker build.
if [[ ! -f /swapfile ]]; then
	log "adding 2 GiB of swap for the frontend build"
	dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
	chmod 600 /swapfile
	mkswap /swapfile >/dev/null
	swapon /swapfile
	grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >>/etc/fstab
fi

# ------------------------------------------------------------------- secrets --
# The database password is generated here and never leaves the instance: it is
# not a stack parameter (those are readable from the CloudFormation API) and
# not in the repository. Generated once — a later run keeps the existing one,
# because changing it would lock the app out of the volume Postgres already
# initialised with it.
umask 077
install -d -m 700 /etc/loopboard
SECRET_FILE=/etc/loopboard/postgres_password
if [[ ! -s $SECRET_FILE ]]; then
	log "generating the database password"
	openssl rand -hex 24 >"$SECRET_FILE"
	chmod 600 "$SECRET_FILE"
fi
POSTGRES_PASSWORD=$(cat "$SECRET_FILE")

# ---------------------------------------------------------------- compose env --
# Caddy's site address: a domain gets automatic HTTPS, no domain gets plain
# HTTP on the instance's address, which is what a stack deployed without a
# DomainName serves until one is set.
if [[ -n $DOMAIN_NAME ]]; then
	site=$DOMAIN_NAME
	origin=https://$DOMAIN_NAME
else
	site=:80
	origin=
fi

seed=0
[[ ${SEED_DEMO_DATA,,} == true ]] && seed=1

log "writing $DEPLOY_DIR/.env (site: $site, seed: $seed)"
cat >"$DEPLOY_DIR/.env" <<ENV
# Written by bootstrap.sh — edit deploy.env and re-run rather than this file.
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
LOOPBOARD_SITE=$site
LETSENCRYPT_EMAIL=$LETSENCRYPT_EMAIL
APP_ORIGIN=$origin
LOOPBOARD_SEED=$seed
ENV
chmod 600 "$DEPLOY_DIR/.env"

# ----------------------------------------------------------------------- up ---
# `--wait` holds until the health checks pass, so a failure to start is this
# script's failure — and, through the wait condition, the stack's — rather than
# a green deployment in front of a container in a restart loop.
log "building and starting the stack"
"${COMPOSE[@]}" up -d --build --wait --wait-timeout 300

log "running containers"
"${COMPOSE[@]}" ps

if [[ -n $DOMAIN_NAME ]]; then
	log "Caddy will obtain a certificate for $DOMAIN_NAME once its DNS record
	points at this instance; until then the site answers on HTTP only.
	Watch it with: docker compose -f $DEPLOY_DIR/docker-compose.prod.yaml logs -f caddy"
fi
