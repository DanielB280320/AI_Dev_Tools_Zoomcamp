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

```bash
aws cloudformation deploy \
  --stack-name loopboard \
  --template-file deploy/loopboard.cfn.yaml \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
      VpcId=vpc-xxxxxxxx \
      SubnetId=subnet-xxxxxxxx \
      DomainName=loopboard.example.com \
      LetsEncryptEmail=you@example.com
```

`DomainName` is optional — without it the site answers on plain HTTP at the
Elastic IP, which is enough to see it working. The stack takes 10-15 minutes,
most of it the frontend build; it fails rather than finishing green if the app
does not come up, because the wait condition is signalled from the end of
`bootstrap.sh` after `docker compose up --wait`.

Then read the addresses out of the stack:

```bash
aws cloudformation describe-stacks --stack-name loopboard \
  --query 'Stacks[0].Outputs' --output table
```

### DNS

Point an `A` record for the domain at the `PublicIp` output. Caddy retries
until it resolves, then obtains the certificate within a minute — nothing needs
restarting. Watch it happen:

```bash
aws ssm start-session --target i-xxxxxxxx    # no SSH key, no open port 22
sudo docker compose -f /opt/loopboard/app/deploy/docker-compose.prod.yaml logs -f caddy
```

If the zone is in Route 53, pass `HostedZoneId=...` instead and the stack
creates the record itself.

## Operating it

Everything below runs on the instance, reached with `aws ssm start-session`
(or SSH, if the stack was deployed with `SshAllowedCidr`).

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

## CI/CD

`.github/workflows/loopboard.yml`, at the repository root, runs on every push
and pull request that touches this app:

1. **Backend tests** (`pytest`) and **frontend tests** (type check and Vitest) run in
   parallel.
2. **Integration and e2e tests**: builds the compose stack, drives the frontend's
   API client against it (`frontend/scripts/smoke-api.mjs`), then runs the
   Playwright suite in its container.
3. **Deploy** runs on `main` only. It assumes an IAM role through GitHub's OIDC
   token, then uses SSM Run Command on the instance to check out the commit the
   run tested and run `bootstrap.sh`, which is the same redeploy as the manual one
   above.
4. **Verify** requests `/health` through the public URL (CloudFront when the stack
   has it) and fails the run unless it reports `"status": "ok"`.

Steps 3 and 4 are skipped until the role exists. To set it up:

```bash
aws cloudformation deploy \
  --stack-name loopboard-github-oidc \
  --template-file deploy/github-oidc.cfn.yaml \
  --capabilities CAPABILITY_IAM

aws cloudformation describe-stacks --stack-name loopboard-github-oidc \
  --query "Stacks[0].Outputs[?OutputKey=='DeployRoleArn'].OutputValue" --output text
```

Then, on GitHub, go to Settings > Secrets and variables > Actions > Variables and
set `AWS_DEPLOY_ROLE_ARN` to that ARN. The role trusts only jobs in this
repository's `production` environment. It can read the `loopboard` stack and
send commands to that stack's instance, and nothing else. If the account already
registers `token.actions.githubusercontent.com`, pass
`ExistingOidcProviderArn=...` so the stack reuses that provider.

**On an AWS project (the new sign-up experience), the stack only deploys after
you activate advanced features in AWS Settings.** The managed service control
policies on both the Free and the Paid plan deny `iam:*Provider*`, which blocks
creating the OIDC identity provider.

**Back up** the database, which is the only state worth keeping:

```bash
sudo docker compose -f docker-compose.prod.yaml exec -T db \
  pg_dump -U loopboard loopboard | gzip > loopboard-$(date +%F).sql.gz
```

## What is different from the local stack

| | `docker-compose.yaml` | `deploy/docker-compose.prod.yaml` |
| --- | --- | --- |
| Postgres password | `sdip`, in the file | generated per instance into `/etc/loopboard/postgres_password` |
| Postgres port | published on 5432 | not published at all |
| Demo data | seeded | off, unless `SeedDemoData=true` |
| Front door | the app on `:8000` | Caddy on `:80`/`:443`, app not published |
| TLS | none | Let's Encrypt, renewed automatically |

## Cost

About **$15/month** in us-east-2: t3.small on-demand (~$15), 30 GiB gp3 (~$2.40),
the Elastic IP free while attached to a running instance. No load balancer, no
NAT gateway, no managed database — the three line items that usually dominate a
small deployment.

Tear it all down with `aws cloudformation delete-stack --stack-name loopboard`,
which takes the database volume with it.

## Before a real audience

- `POST /auth/register` is open to anyone who finds the URL. Put it behind a
  check, or accept that the site is open to registration.
- `SeedDemoData=false` is the default for a reason: the seeded interviewers
  share the password printed in the README.
- Nothing backs up `pgdata` on its own.
