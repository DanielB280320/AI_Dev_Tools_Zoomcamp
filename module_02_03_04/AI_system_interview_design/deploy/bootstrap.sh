#!/bin/bash
# Bring the deployed stack up on a fresh Amazon Linux 2023 instance.
#
# The CloudFormation template's UserData installs git, clones the repository to
# /opt/loopboard/app and runs this. CI deploys by running it again with the
# image to run:
#
#   LOOPBOARD_IMAGE=<account>.dkr.ecr.<region>.amazonaws.com/loopboard:<tag> \
#     sudo -E deploy/bootstrap.sh
#
# The image is pulled, never built, and recorded in /etc/loopboard/image, so a
# plain re-run restarts the same image. With no image given and none recorded —
# a fresh instance before its first CI deploy — the app is built from the
# checkout instead.
#
# Everything else comes from /etc/loopboard/deploy.env, which UserData writes
# from the stack's parameters. Only the ECR login calls AWS, so without an image
# it also runs on any other Debian/RHEL-ish box with the same file in place.
set -euo pipefail

ENV_FILE=/etc/loopboard/deploy.env
DEPLOY_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
COMPOSE=(docker compose -f "$DEPLOY_DIR/docker-compose.prod.yaml")

# LOOPBOARD_ENV, DOMAIN_NAME, LETSENCRYPT_EMAIL and SEED_DEMO_DATA, all
# possibly empty, plus the OTLP settings if someone has added them.
# shellcheck source=/dev/null
[[ -f $ENV_FILE ]] && source "$ENV_FILE"
LOOPBOARD_ENV=${LOOPBOARD_ENV:-}
DOMAIN_NAME=${DOMAIN_NAME:-}
LETSENCRYPT_EMAIL=${LETSENCRYPT_EMAIL:-}
SEED_DEMO_DATA=${SEED_DEMO_DATA:-false}
OTEL_EXPORTER_OTLP_ENDPOINT=${OTEL_EXPORTER_OTLP_ENDPOINT:-}
OTEL_EXPORTER_OTLP_HEADERS=${OTEL_EXPORTER_OTLP_HEADERS:-}
# Fault injection for testing alerts (backend/app/config.py); 0 or unset is off.
LOOPBOARD_FAULT_ELEMENT_FAILURE_RATE=${LOOPBOARD_FAULT_ELEMENT_FAILURE_RATE:-0}

log() { printf '\n=== %s\n' "$*"; }

# ------------------------------------------------------------------ telemetry --
# An endpoint in deploy.env wins. Otherwise the observability stack's
# Collector, if one is deployed: deploy/observability.cfn.yaml publishes its
# private address as this SSM parameter. Absent, unreadable, or off AWS
# altogether, telemetry stays off and the deploy carries on — monitoring is
# never a reason for the app not to start.
OTLP_PARAMETER=/loopboard/observability/otlp-endpoint
if [[ -z $OTEL_EXPORTER_OTLP_ENDPOINT ]] && command -v aws >/dev/null; then
	imds_token=$(curl -fsS --max-time 2 -X PUT -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' \
		http://169.254.169.254/latest/api/token 2>/dev/null || true)
	if [[ -n $imds_token ]]; then
		imds_region=$(curl -fsS --max-time 2 -H "X-aws-ec2-metadata-token: $imds_token" \
			http://169.254.169.254/latest/meta-data/placement/region)
		OTEL_EXPORTER_OTLP_ENDPOINT=$(aws ssm get-parameter --region "$imds_region" \
			--name "$OTLP_PARAMETER" --query Parameter.Value --output text 2>/dev/null || true)
	fi
fi
log "telemetry: ${OTEL_EXPORTER_OTLP_ENDPOINT:-off} (environment: ${LOOPBOARD_ENV:-unset})"
if [[ $LOOPBOARD_FAULT_ELEMENT_FAILURE_RATE != 0 ]]; then
	log "FAULT INJECTION ON: $LOOPBOARD_FAULT_ELEMENT_FAILURE_RATE of element-adding canvas writes will fail"
fi

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

# --------------------------------------------------------------------- image --
# Given by the deploy, else whatever the last successful deploy ran. Recorded
# only after the stack comes up healthy, below, so a failed deploy leaves the
# previous image as the one a re-run restarts.
IMAGE_FILE=/etc/loopboard/image
IMAGE=${LOOPBOARD_IMAGE:-}
if [[ -z $IMAGE && -s $IMAGE_FILE ]]; then
	IMAGE=$(cat "$IMAGE_FILE")
fi

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

# The Caddyfile imports this. A bare `email` directive is a syntax error, so
# with no address configured the file holds a comment and nothing else.
if [[ -n $LETSENCRYPT_EMAIL ]]; then
	echo "email $LETSENCRYPT_EMAIL" >"$DEPLOY_DIR/caddy-acme.conf"
else
	echo "# no ACME contact address configured" >"$DEPLOY_DIR/caddy-acme.conf"
fi
chmod 644 "$DEPLOY_DIR/caddy-acme.conf"

log "writing $DEPLOY_DIR/.env (site: $site, seed: $seed, image: ${IMAGE:-built here})"
cat >"$DEPLOY_DIR/.env" <<ENV
# Written by bootstrap.sh — edit deploy.env and re-run rather than this file.
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
LOOPBOARD_SITE=$site
LETSENCRYPT_EMAIL=$LETSENCRYPT_EMAIL
APP_ORIGIN=$origin
LOOPBOARD_SEED=$seed
LOOPBOARD_IMAGE=$IMAGE
LOOPBOARD_ENV=$LOOPBOARD_ENV
OTEL_EXPORTER_OTLP_ENDPOINT=$OTEL_EXPORTER_OTLP_ENDPOINT
OTEL_EXPORTER_OTLP_HEADERS=$OTEL_EXPORTER_OTLP_HEADERS
GIT_COMMIT=$(git -C "$DEPLOY_DIR" rev-parse HEAD 2>/dev/null || true)
LOOPBOARD_FAULT_ELEMENT_FAILURE_RATE=$LOOPBOARD_FAULT_ELEMENT_FAILURE_RATE
ENV
chmod 600 "$DEPLOY_DIR/.env"

# ----------------------------------------------------------------------- up ---
# `--wait` holds until the health checks pass, so a failure to start is this
# script's failure — and, through the wait condition, the stack's — rather than
# a green deployment in front of a container in a restart loop.
if [[ -n $IMAGE ]]; then
	# <account>.dkr.ecr.<region>.amazonaws.com/<repository>:<tag>
	registry=${IMAGE%%/*}
	region=${registry#*.dkr.ecr.}
	region=${region%%.*}
	log "pulling $IMAGE"
	aws ecr get-login-password --region "$region" \
		| docker login --username AWS --password-stdin "$registry"
	# `pull` fails outright on a missing image; `up` alone would quietly fall
	# back to building one from the checkout.
	"${COMPOSE[@]}" pull app
	log "starting the stack"
	"${COMPOSE[@]}" up -d --no-build --wait --wait-timeout 300
	echo "$IMAGE" >"$IMAGE_FILE"
else
	log "no image to pull; building the app from the checkout"
	"${COMPOSE[@]}" up -d --build --wait --wait-timeout 300
fi

log "running containers"
"${COMPOSE[@]}" ps

if [[ -n $DOMAIN_NAME ]]; then
	log "Caddy will obtain a certificate for $DOMAIN_NAME once its DNS record
	points at this instance; until then the site answers on HTTP only.
	Watch it with: docker compose -f $DEPLOY_DIR/docker-compose.prod.yaml logs -f caddy"
fi
