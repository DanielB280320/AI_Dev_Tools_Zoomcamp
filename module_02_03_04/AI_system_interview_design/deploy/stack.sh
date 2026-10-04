#!/bin/bash
# Create or update one Loopboard environment's CloudFormation stacks.
#
#   deploy/stack.sh dev           # the app stack (loopboard.cfn.yaml)
#   deploy/stack.sh prod
#   deploy/stack.sh prod ci       # that environment's GitHub deploy user
#   deploy/stack.sh registry      # the ECR repository both environments share
#
# Every input comes from deploy/environments/<env>.env, so a deploy is
# reproducible from the repository rather than from whoever last ran it. The
# environment name is the argument, not a line in the file, so the file cannot
# disagree with the stack it is deploying.
#
# `aws cloudformation deploy` creates the stack if it is absent and otherwise
# updates it through a change set, so running this twice is the redeploy of the
# infrastructure — which is not the same thing as redeploying the app. The app
# is redeployed by bootstrap.sh on the instance (deploy/README.md).
set -euo pipefail

DEPLOY_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

ENVIRONMENT=${1:-}
WHAT=${2:-app}

# One repository for both environments — prod runs the image dev pushed — so it
# belongs to no environment file.
if [[ $ENVIRONMENT == registry ]]; then
	printf 'Deploying stack loopboard-ecr from ecr.cfn.yaml\n'
	aws cloudformation deploy \
		--stack-name loopboard-ecr \
		--template-file "$DEPLOY_DIR/ecr.cfn.yaml" \
		--tags "Application=loopboard"
	aws cloudformation describe-stacks --stack-name loopboard-ecr \
		--query 'Stacks[0].Outputs' --output table
	exit
fi

case $ENVIRONMENT in
	dev | prod) ;;
	*)
		echo "usage: ${BASH_SOURCE[0]##*/} <dev|prod> [app|ci] | registry" >&2
		exit 2
		;;
esac

ENV_FILE="$DEPLOY_DIR/environments/$ENVIRONMENT.env"
[[ -f $ENV_FILE ]] || { echo "no such environment file: $ENV_FILE" >&2; exit 1; }

# STACK_NAME, plus one line per template parameter to override.
# shellcheck source=/dev/null
source "$ENV_FILE"
: "${STACK_NAME:?STACK_NAME is required in $ENV_FILE}"

# The overrides are every KEY=VALUE in the file except the two that name things
# rather than parameterise them, read from the file so a parameter added there
# needs no change here.
overrides=(EnvironmentName="$ENVIRONMENT")
while read -r key; do
	[[ $key == STACK_NAME ]] && continue
	overrides+=("$key=${!key}")
done < <(sed -n 's/^\([A-Za-z_][A-Za-z0-9_]*\)=.*/\1/p' "$ENV_FILE")

case $WHAT in
	app)
		stack=$STACK_NAME
		template=$DEPLOY_DIR/loopboard.cfn.yaml
		capabilities=CAPABILITY_IAM
		;;
	ci)
		stack=$STACK_NAME-github-deploy
		template=$DEPLOY_DIR/github-deploy-user.cfn.yaml
		capabilities=CAPABILITY_NAMED_IAM
		# This template takes only these two; the app's network and instance
		# parameters would be rejected as unknown.
		overrides=(EnvironmentName="$ENVIRONMENT" AppStackName="$STACK_NAME")
		;;
	*)
		echo "second argument is 'app' or 'ci', not '$WHAT'" >&2
		exit 2
		;;
esac

# A value nobody filled in would otherwise reach CloudFormation and fail there,
# several minutes later, with an error about the value rather than the file.
for override in "${overrides[@]}"; do
	if [[ $override == *=REPLACE_ME ]]; then
		echo "${override%%=*} is still REPLACE_ME in $ENV_FILE" >&2
		echo "See deploy/README.md, \"Environments\", for where its value comes from." >&2
		exit 1
	fi
done

printf 'Deploying %s stack %s from %s\n' "$ENVIRONMENT" "$stack" "${template#"$DEPLOY_DIR"/}"
printf '  %s\n' "${overrides[@]}"

aws cloudformation deploy \
	--stack-name "$stack" \
	--template-file "$template" \
	--capabilities "$capabilities" \
	--tags "Environment=$ENVIRONMENT" "Application=loopboard" \
	--parameter-overrides "${overrides[@]}"

aws cloudformation describe-stacks --stack-name "$stack" \
	--query 'Stacks[0].Outputs' --output table
