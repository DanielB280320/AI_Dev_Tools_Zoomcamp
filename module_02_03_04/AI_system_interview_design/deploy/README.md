# Deploying Loopboard to AWS

One EC2 instance running the same docker-compose stack the e2e suite drives
locally, with Caddy in front of it for HTTPS. `loopboard.cfn.yaml` is the whole
deployment: it creates the instance, an Elastic IP, a security group and an
instance profile, then boots the app by cloning this repository and running
`bootstrap.sh`.

```
        :443  ┌──────────────────────── EC2 (t3.small, Amazon Linux 2023) ──┐
internet ────▶│ caddy ──▶ app (FastAPI + built SPA) ──▶ db (Postgres 16)    │
        :80   │  TLS      one process, one worker       volume: pgdata      │
              └─────────────────────────────────────────────────────────────┘
```

That template is deployed **twice**, once per environment. See
[Environments](#environments) for what each one is and how a change reaches it.

## Environments

| | dev | prod |
| --- | --- | --- |
| URL | https://d1u9mpb2rc8ljk.cloudfront.net/ | the `CloudFrontUrl` output of `loopboard-prod` |
| App stack | `loopboard` | `loopboard-prod` |
| CI stack | `loopboard-github-deploy` | `loopboard-prod-github-deploy` |
| Parameters | `environments/dev.env` | `environments/prod.env` |
| Deployed by | every push to `main` | a manual workflow dispatch |
| Demo data | seeded | off |

Nothing is shared. Each environment is its own CloudFormation stack, and every
resource in the template is either named from the stack name or left unnamed, so
the two get their own instance, their own Elastic IP, their own CloudFront
distribution and their own Postgres volume. A change to one cannot reach the
other, and neither can read the other's database.

They do share the VPC and subnet, and the repository the instances build from.
The subnet is shared because a second public subnet would be one more thing to
maintain and would isolate nothing that matters: the instances are separate
hosts with separate security groups either way, and neither one can reach the
other's Postgres, which is published to its own compose network only.

**dev keeps the stack name `loopboard`.** CloudFormation cannot rename a stack,
and deleting and recreating this one would hand out a fresh `*.cloudfront.net`
domain — but that domain *is* the dev URL above. So the original stack stays
exactly where it is; only its role has a name now.

### The three account-specific values

`stack.sh` refuses to deploy while an environment file still says `REPLACE_ME`,
because those values belong to the account rather than to the app. In a fresh
clone, fill them in from the account:

```bash
# VpcId and SubnetId — the default VPC and one of its public subnets. Both
# environments use the same pair; see above for why.
aws ec2 describe-vpcs --filters Name=is-default,Values=true \
  --query 'Vpcs[0].VpcId' --output text
aws ec2 describe-subnets --filters Name=vpc-id,Values=<that vpc> \
  --query 'Subnets[].{Id:SubnetId,AZ:AvailabilityZone,Public:MapPublicIpOnLaunch}' \
  --output table

# CloudFrontOriginPrefixListId — AWS's managed list of CloudFront's
# origin-facing addresses, which differs per Region.
aws ec2 describe-managed-prefix-lists \
  --filters Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing \
  --query 'PrefixLists[0].PrefixListId' --output text
```

The already-deployed dev stack is the other source, and the authoritative one
for dev — its values are the ones the running instance actually uses:

```bash
aws cloudformation describe-stacks --stack-name loopboard \
  --query 'Stacks[0].Parameters' --output table
```

## Why one instance, and not a load balancer

`backend/app/events.py` keeps each session's SSE subscribers in a dict inside
the process holding the open streams. Two app processes means two dicts: a
candidate connected to the second one never hears about an edit that landed on
the first, and the board silently stops updating for them. So this deployment
runs exactly one container with exactly one uvicorn worker, and there is no
autoscaling group.

Lifting that limit is one change — publish through Postgres `LISTEN/NOTIFY` (or
Redis) inside `EventBroker.publish` and subscribe in the stream handler. Until
then, do not raise the replica count, add `--workers`, or put this behind a
target group with more than one target.

## Deploy

Each environment's parameters live in `environments/<env>.env`, so a deploy is
reproducible from the repository rather than from whoever last ran it.
`stack.sh` reads one of those files and hands it to `aws cloudformation deploy`,
which creates the stack if it is absent and otherwise updates it:

```bash
make deploy-dev         # or: deploy/stack.sh dev
make deploy-prod        # or: deploy/stack.sh prod
```

Both print the stack's outputs when they finish, so the address is the last
thing on screen. To read them again later:

```bash
aws cloudformation describe-stacks --stack-name loopboard-prod \
  --query 'Stacks[0].Outputs' --output table
```

A first deploy takes 10-15 minutes, most of it the frontend build. It fails
rather than finishing green if the app does not come up, because the wait
condition is signalled from the end of `bootstrap.sh` after
`docker compose up --wait`.

This deploys the *infrastructure*. Redeploying the *app* onto an instance that
already exists is a different and much faster thing — CI does it on every push
to dev, and `bootstrap.sh` does it by hand (see [Operating it](#operating-it)).

`EnableCloudFront=true` in both environment files is what gives each one an
HTTPS address without owning a domain. To serve a domain of your own instead,
add `DomainName=` and `LetsEncryptEmail=` to that environment's file and drop
`CloudFrontOriginPrefixListId` — Caddy cannot answer the ACME challenge on a
port 80 only CloudFront may open.

### DNS

Point an `A` record for the domain at the `PublicIp` output. Caddy retries
until it resolves, then obtains the certificate within a minute — nothing needs
restarting. Watch it happen:

```bash
aws ssm start-session --target i-xxxxxxxx    # no SSH key, no open port 22
sudo docker compose -f /opt/loopboard/app/deploy/docker-compose.prod.yaml logs -f caddy
```

If the zone is in Route 53, add `HostedZoneId=` to that environment's file
instead and the stack creates the record itself.

## Operating it

Everything below runs on the instance, reached with `aws ssm start-session` (or
SSH, if the stack was deployed with `SshAllowedCidr`). Both environments use the
same paths, so the only thing that differs is which instance you open — get it
from the stack, so you cannot open the wrong one by accident:

```bash
stack=loopboard-prod        # or: loopboard, for dev
aws ssm start-session --target "$(aws cloudformation describe-stack-resource \
  --stack-name "$stack" --logical-resource-id Instance \
  --query StackResourceDetail.PhysicalResourceId --output text)"
```

`cat /etc/loopboard/deploy.env` on the instance says which environment it is,
if you lose track once you are in.

```bash
cd /opt/loopboard/app/deploy
sudo docker compose -f docker-compose.prod.yaml ps
sudo docker compose -f docker-compose.prod.yaml logs -f app
sudo docker compose -f docker-compose.prod.yaml exec db psql -U loopboard
```

**Redeploy** after pushing a commit — the instance builds from the repository,
so there is no image to push anywhere:

```bash
cd /opt/loopboard/repo && sudo git pull
sudo /opt/loopboard/app/deploy/bootstrap.sh
```

`bootstrap.sh` is idempotent: it keeps the generated database password, rebuilds
the images and waits for the health checks. It is also how a setting changes —
edit `/etc/loopboard/deploy.env` (the domain, the Let's Encrypt address, whether
to seed demo data) and run it again.

**Back up** the database, which is the only state worth keeping:

```bash
sudo docker compose -f docker-compose.prod.yaml exec -T db \
  pg_dump -U loopboard loopboard | gzip > loopboard-$(date +%F).sql.gz
```

## CI/CD

`.github/workflows/loopboard.yml`, at the repository root, runs on every push
and pull request that touches this app:

1. **Backend tests** (`pytest`) and **frontend tests** (type check and Vitest) run in
   parallel.
2. **Integration and e2e tests**: builds the compose stack, drives the frontend's
   API client against it (`frontend/scripts/smoke-api.mjs`), then runs the
   Playwright suite in its container.
3. **Deploy** runs on `main` only. It signs in as that environment's IAM user
   from `github-deploy-user.cfn.yaml`, then sends that stack's
   `loopboard-redeploy-<env>` SSM document to the instance. The document checks
   out the commit the run tested, refusing one that is not on `main`, and runs
   `bootstrap.sh`: the same redeploy as the manual one above.
4. **Verify** requests `/health` through the public URL (CloudFront when the stack
   has it) and fails the run unless it reports `"status": "ok"`.

### Which environment a run deploys

```
push to main            ─▶ dev     automatic
Run workflow ▸ prod     ─▶ prod    manual only
```

A push never touches prod. Deploying prod means opening **Actions ▸ loopboard ▸
Run workflow** and choosing `prod` — and even then the whole test pipeline runs
first, so prod only ever receives a commit that went green. The dispatch must be
on `main`; the SSM document refuses a commit that is not in `main`'s history
regardless.

The job's GitHub environment is `dev` or `prod`, which is where its AWS
credentials come from — so a dev run holds no key that could reach prod. Add a
required reviewer to the `prod` environment (Settings ▸ Environments ▸ prod ▸
Required reviewers) to make a prod deploy wait for an approval as well.

### One-time setup, per environment

Each environment has its own deploy user, so the prod key exists only inside the
`prod` environment's secrets:

```bash
make deploy-ci-dev      # creates loopboard-github-deploy-dev  + loopboard-redeploy-dev
make deploy-ci-prod     # creates loopboard-github-deploy-prod + loopboard-redeploy-prod
```

Then mint each user's key straight into its GitHub environment, so the secret
never lands in a file or on screen:

```bash
REPO=DanielB280320/AI_Dev_Tools_Zoomcamp

for env in dev prod; do
  gh api -X PUT "repos/$REPO/environments/$env" >/dev/null   # create it if absent
  read -r key_id secret < <(aws iam create-access-key \
    --user-name "loopboard-github-deploy-$env" \
    --query 'AccessKey.[AccessKeyId,SecretAccessKey]' --output text)
  gh secret set AWS_ACCESS_KEY_ID     --repo "$REPO" --env "$env" --body "$key_id"
  gh secret set AWS_SECRET_ACCESS_KEY --repo "$REPO" --env "$env" --body "$secret"
  unset key_id secret
done
```

Then **delete the repository-level `AWS_ACCESS_KEY_ID` and
`AWS_SECRET_ACCESS_KEY`**, if they are still there from the single-environment
setup:

```bash
gh secret delete AWS_ACCESS_KEY_ID     --repo "$REPO"
gh secret delete AWS_SECRET_ACCESS_KEY --repo "$REPO"
```

Leaving them would mean a prod run silently falls back to them when the `prod`
environment has none of its own. That fails safely — the dev user is not allowed
to send prod's document — but it fails confusingly.

(Without `gh`: Settings ▸ Environments ▸ New environment, then add the two
secrets under it.)

### What a leaked key can do

Each user has no console password and is allowed exactly the four calls its
deploy job makes, against its own environment only:

| Permission | Scoped to |
| --- | --- |
| `cloudformation:DescribeStacks`, `DescribeStackResource` | that environment's app stack |
| `ssm:SendCommand` | the `loopboard-redeploy-<env>` document, on the instance tagged with that stack |
| `ssm:GetCommandInvocation` | `*`, because the action has no resource type |

So even a leaked key can only redeploy a commit that is already on `main`, onto
one environment's instance. It cannot run other commands there, pass a role,
reach the other environment, or change anything in AWS. They are long-lived
keys, though, so rotate them now and then: create a second key, update that
environment's two secrets, then `aws iam delete-access-key` the old one.

Why not a GitHub OIDC role, which would need no stored key? On an AWS project
(the new sign-up experience) the managed service control policies deny
`iam:*Provider*`, which blocks creating GitHub's OIDC identity provider, and on
the Free plan that cannot be lifted.

## What is different from the local stack

| | `docker-compose.yaml` | `deploy/docker-compose.prod.yaml` |
| --- | --- | --- |
| Postgres password | `sdip`, in the file | generated per instance into `/etc/loopboard/postgres_password` |
| Postgres port | published on 5432 | not published at all |
| Demo data | seeded | off, unless `SeedDemoData=true` |
| Front door | the app on `:8000` | Caddy on `:80`/`:443`, app not published |
| TLS | none | Let's Encrypt, renewed automatically |

## Cost

About **$18/month per environment** in us-east-2: t3.small on-demand (~$15),
30 GiB gp3 (~$2.40), CloudFront's first TB free then cents at this traffic, and
the Elastic IP free while attached to a running instance. No load balancer, no
NAT gateway, no managed database — the three line items that usually dominate a
small deployment.

Two environments is therefore about **$36/month**. Every resource carries an
`Environment` tag, so Cost Explorer can split the bill between them once the tag
is activated as a cost allocation tag (Billing ▸ Cost allocation tags).

To stop paying for one without losing it, stop its instance — the volume and the
Elastic IP survive, and the EIP starts costing about $3.60/month while detached
from a running instance. To delete one outright, database and all:

```bash
aws cloudformation delete-stack --stack-name loopboard-prod
aws cloudformation delete-stack --stack-name loopboard-prod-github-deploy
```

## Before a real audience

- `POST /auth/register` is open to anyone who finds the URL. Put it behind a
  check, or accept that the site is open to registration.
- `SeedDemoData=false` in `environments/prod.env` is deliberate: the seeded
  interviewers share the password printed in the README. dev seeds them on
  purpose; prod must not.
- Nothing backs up `pgdata` on its own, on either environment.
- Migrations: the app creates its tables on start and there is no migration
  step, so a schema change that is not additive will meet an existing prod
  volume. dev is where that surfaces — it takes the same commit first.
