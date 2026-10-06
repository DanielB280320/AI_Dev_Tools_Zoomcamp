# Build, Ship and Operate a Production Full-Stack App with AI Coding Agents

A reusable playbook: the same steps as `support_prompts.md`, generalized so they work for **any** full-stack app. Each step has the goal, a prompt to paste into your coding agent (Claude Code, Codex, Cursor, …), and a **Done when** check so you know when to move on.

> Placeholders look like `[APP_NAME]`, `[DOMAIN_ENTITY]`, `[REGION]`. Replace them before pasting.

---

## 0. The Big Picture

### The lifecycle

```mermaid
flowchart LR
    subgraph M2["Module 2 · Design & Build"]
        A[Spec] --> B[Frontend + mocks]
        B --> C[AGENTS.md]
        C --> D[OpenAPI contract]
        D --> E[Backend]
        E --> F[Makefile]
        F --> G[Wire FE ↔ BE]
        G --> H[Database]
    end
    subgraph M3["Module 3 · Package & Deploy"]
        I[Dockerfile] --> J[Postgres]
        J --> K[Docker Compose]
        K --> L[Integration + E2E tests]
        L --> N[Cloud deploy]
        N --> O[CI/CD]
    end
    subgraph M4["Module 4 · Operate"]
        P[Dev / Prod envs] --> Q[Image promotion]
        Q --> R[OpenTelemetry]
        R --> S[Observability stack]
        S --> T[Alerts]
        T --> U[On-call agent]
    end
    H --> I
    O --> P
```

### The target architecture

```mermaid
flowchart TB
    user([Users]) -->|HTTPS| cdn[CDN / TLS edge<br/>CloudFront]
    cdn --> app

    subgraph cloud["Cloud project · one Region"]
        subgraph dev["Dev environment"]
            app[App container<br/>API + static frontend]
            db[(Postgres)]
            app --> db
        end
        subgraph prod["Prod environment"]
            app2[App container] --> db2[(Postgres)]
        end
        reg[(Container registry<br/>ECR)]
        subgraph obs["Observability stack"]
            col[OTel Collector] --> prom[Prometheus]
            col --> loki[Loki]
            col --> tempo[Tempo]
            prom --> graf[Grafana]
            loki --> graf
            tempo --> graf
        end
    end

    ci[CI/CD<br/>GitHub Actions] -->|push image| reg
    reg -->|pull| app
    reg -->|pull same tag| app2
    app -. OTLP .-> col
    app2 -. OTLP .-> col
    prom -->|firing alerts| agent[On-call agent<br/>headless coding agent]
    agent -->|branch + fix| ci
```

### Golden rules for working with coding agents

| Rule | Why it matters |
|---|---|
| **Spec before code** | The agent builds what you describe; vague input gives generic output. |
| **One step per prompt** | Small, reviewable diffs. Easier to roll back when the agent goes off track. |
| **Contracts over inference** | An `openapi.yaml` is cheaper (tokens) and more precise than "read the frontend and guess". |
| **Tests in every prompt** | Tests are how the agent verifies its own work, and how you verify the agent. |
| **Commit after every green step** | Git is your undo button. Agents make mistakes; cheap rollback makes them harmless. |
| **Persist context in files** | `AGENTS.md` / `CLAUDE.md` survive between sessions; chat history does not. |
| **Least privilege for agents** | An agent with cloud credentials can do anything those credentials allow. |

### The per-step loop

```mermaid
flowchart LR
    P[Prompt] --> G[Agent generates]
    G --> R[You review the diff]
    R --> T{Tests pass?}
    T -- no --> F[Paste the failure back] --> G
    T -- yes --> C[git commit] --> N[Next step]
```

---

## Module 2: Design & Build

### 1. Start with a specification

**Goal:** a written spec (`docs/spec.md`) that both you and the agent agree on before any code exists.

A good spec answers: *who* uses it, *what* they can do, *what data* exists, *what must happen in real time*, and *what is out of scope*.

    I want to build [APP_NAME]: [one-paragraph description of the problem it solves].

    Users:
    - [ROLE_1] can [actions]
    - [ROLE_2] can [actions]

    Core features:
    - [feature 1]
    - [feature 2]
    - [real-time / collaboration / notifications requirements, if any]

    Out of scope for v1: [things we will NOT build yet]

    Help me write a specification. Ask me clarifying questions first, then write
    docs/spec.md with: user stories, domain entities and their fields, main user
    flows, non-functional requirements (auth, performance, real-time), and open questions.

**Done when:** you can read `spec.md` and find nothing you disagree with, and the "open questions" list is empty or consciously deferred.

> 💡 Ask the agent to *ask you questions first*. It surfaces ambiguities you didn't know you had.

### 2. Frontend first

**Goal:** a clickable app running entirely on mocks, so you validate the UX before investing in a backend.

```mermaid
flowchart LR
    UI[Components / pages] --> SVC[services layer<br/>api.ts]
    SVC --> MOCK[Mock implementation]
    SVC -. later .-> REAL[HTTP client → backend]
```

    # Sample 1 (fresh agent / tool like Lovable, Bolt, v0):
    Create a [APP_NAME] application using [React + Vite + TypeScript].

    [Paste docs/spec.md here.]

    Centralize every backend call in one services layer, and create a mock
    implementation of it so the whole app runs without a real backend.

    Add tests.

    # Sample 2 (inside an existing repo):
    Create the frontend for this spec in frontend/. I'll build the backend later —
    for now, mock all backend calls behind a single services layer.

**Done when:** `npm run dev` shows every main flow from the spec working against mocks, and `npm test` passes.

### Move the frontend into the project

Use the same structure for every project:

    /backend       # backend application and its tests
    /docs          # supporting documentation
        spec.md
    /frontend      # frontend application
    /e2e           # end-to-end tests (Module 3)
    /deploy        # infrastructure as code (Module 3)
    /observability # monitoring stack (Module 4)
    AGENTS.md      # instructions for coding agents
    openapi.yaml   # API agreement between frontend and backend
    Makefile       # one entry point for every command

To run a frontend exported from Lovable (or similar):

    cd frontend
    npm i
    npm run dev

### 3. Context engineering: AGENTS.md / CLAUDE.md

**Goal:** give every future agent session the project's conventions without repeating them.

`CLAUDE.md` for Claude Code, `AGENTS.md` for most other agents (you can symlink one to the other). Start small and add a rule every time you correct the agent twice for the same thing.

    # [APP_NAME]

    ## Stack
    - backend: Python + FastAPI, managed with uv
    - frontend: React + Vite + TypeScript, managed with npm
    - db: SQLAlchemy; SQLite locally, Postgres in Docker/cloud

    ## Commands
    uv sync
    uv add <PACKAGE-NAME>
    uv run python <PYTHON-FILE>
    make dev        # run frontend + backend
    make test       # run all tests

    ## Conventions
    - openapi.yaml is the source of truth for the API; update it first
    - every change comes with tests
    - regularly commit code to git, small commits with clear messages
    - never commit secrets; config comes from environment variables

**Done when:** a fresh agent session can run the app and the tests without you explaining anything.

### 4. OpenAPI specification

**Goal:** a machine-readable contract between frontend and backend.

```mermaid
flowchart LR
    FE[Frontend services layer] -->|extract| OA[openapi.yaml]
    OA -->|implement| BE[Backend]
    OA -->|generate / validate| CL[Typed client + contract tests]
```

    Read the frontend's services layer in frontend/.

    Create openapi.yaml at the repository root.

    Specify the backend this frontend expects: every endpoint, method, path,
    request body, response body, error responses, and which endpoints need
    authentication. Include real-time channels (WebSocket/SSE) as documented
    extensions if the app uses them.

The backend now gets a precise target instead of inferring it from frontend code: fewer tokens, fewer surprises, and a clear picture of what the backend needs.

**Done when:** every call in the services layer maps to an operation in `openapi.yaml`.

### 5. The backend

**Goal:** a working API that satisfies the contract, with auth and tests.

    Build a FastAPI backend in backend/ that implements openapi.yaml.

    Use an in-memory store and seed it with data so the frontend has something
    to show. Add authentication with hashed passwords and bearer tokens for the
    endpoints that need it.

    Split the code into modules: routers, models (schemas), store, auth, config.

    Write tests, including one that checks the app's routes match openapi.yaml.

Suggested layout:

    backend/
      app/
        main.py        # app factory, middleware, router registration
        config.py      # settings from environment variables
        auth.py        # hashing, tokens, dependencies
        models.py      # request/response schemas
        store.py       # data access (in-memory now, DB later)
        routers/       # one file per resource
      tests/

**Done when:** `uv run pytest` passes and `/docs` (Swagger UI) shows every endpoint from the contract.

### 6. Makefile

**Goal:** one discoverable entry point for every command, for humans, agents and CI alike.

    Create a Makefile so I can easily run the app. Include: help (default),
    install, dev (frontend + backend together), test, lint, and clean.
    Document each target.

**Done when:** `make` prints the list of targets and `make dev` starts everything.

### 7. Connecting frontend and backend

    Switch the frontend to use the real backend client. Keep the mock
    implementation available behind a flag (e.g. VITE_USE_MOCKS=true) for
    frontend-only development and tests. Configure CORS on the backend for the
    dev server's origin.

**Done when:** the main flows work end-to-end in the browser with the backend running, and the frontend tests still pass.

### 8. Database

**Goal:** persistent data, behind an abstraction that lets you switch engines.

    Replace the in-memory store with a database. Use SQLite and SQLAlchemy.
    Use an environment variable ([APP]_DATABASE_URL) to configure which DB the
    server connects to. Make it database-agnostic — later we will add Postgres.
    Add migrations with Alembic. Seed demo data only when the DB is empty.

**Done when:** data survives a backend restart and the test suite runs against a fresh database.

---

## Module 3: Package, Test & Deploy

### 1. Creating the Dockerfile

**Goal:** one image that contains everything needed to run the app.

```mermaid
flowchart LR
    subgraph s1["Stage 1 · node"]
        N1[npm ci] --> N2[npm run build] --> N3[/dist/]
    end
    subgraph s2["Stage 2 · python-slim"]
        P1[uv sync --frozen] --> P2[copy backend]
        P2 --> P3[copy dist → static/]
        P3 --> P4[run as non-root<br/>uvicorn]
    end
    N3 --> P3
```

    Create a multi-stage Dockerfile that builds the frontend with Node, then
    builds a slim Python image with the backend and the frontend static files.

    The backend should serve the frontend. Run as a non-root user, add a
    HEALTHCHECK against a /health endpoint, and add a .dockerignore.

### 2. Building and running the image

    Build and run this Dockerfile, fix anything that fails, and document the
    build and run commands in README.md.

**Done when:** `docker run -p 8000:8000 [APP_NAME]` serves the full app from a single port.

### 3. Switch from SQLite to Postgres

Run Postgres locally (or ask the agent to add a `make db-up` target that does it):

    docker run -d \
    --name [APP_NAME]-db \
    -e POSTGRES_USER=app \
    -e POSTGRES_PASSWORD=app \
    -e POSTGRES_DB=app \
    -p 5432:5432 \
    -v [APP_NAME]-pgdata:/var/lib/postgresql/data \
    postgres:16-alpine

    Add Postgres support to the backend. Run the test suite against both SQLite
    and Postgres.

    # Point the app at Postgres when running locally:
    export [APP]_DATABASE_URL=postgresql://app:app@localhost:5432/app

    # Run frontend and backend at the same time:
    make dev

### 4. Docker Compose

    Create docker-compose.yaml with two services: Postgres and the app.
    The app waits for Postgres to be healthy, reads its config from
    environment variables, and Postgres data lives in a named volume.

**Done when:** `docker compose up` gives you a working app on a clean machine.

### 5. Integration and end-to-end tests

**Goal:** confidence that the *assembled* system works, not just its parts.

```mermaid
flowchart TB
    E2E["E2E · Playwright<br/>few, slow, real browser"]
    INT["Integration · API against Compose stack<br/>some, real DB"]
    UNIT["Unit · backend + frontend<br/>many, fast, isolated"]
    E2E --- INT --- UNIT
    style E2E fill:#f8d7da,stroke:#842029
    style INT fill:#fff3cd,stroke:#664d03
    style UNIT fill:#d1e7dd,stroke:#0f5132
```

    # Prompt 1:
    Create integration tests that run against docker-compose.yaml.
    What scenarios should we test? Propose a list first, then implement them.

    # Prompt 2:
    Add an end-to-end test that runs against docker-compose.yaml.

    Use Playwright to cover the most important user journey:

    1. [ROLE_1] logs in (browser session 1).
    2. [ROLE_1] creates a [DOMAIN_ENTITY].
    3. [ROLE_1] shares it (link / invite).
    4. [ROLE_2] opens it from a separate browser (session 2).
    5. [ROLE_2] changes something.
    6. Verify [ROLE_1] sees the change (session 1).

    Put the tests in e2e/ at the repository root and add a `make e2e` target.

### 6. Deploying the app

**Goal:** the app running in the cloud, defined as code, reachable over HTTPS.

First give the agent access to your cloud. For AWS:

    Set up Agent Toolkit for AWS by following instructions:
    https://raw.githubusercontent.com/aws/agent-toolkit-for-aws/refs/heads/main/setup-instructions/setup.md

    Your AWS Region is: [REGION]
    AWS experience: [The new AWS experience | classic]

Then work through the deployment in small prompts:

    # Prompt 1: explore options before committing
    I want to deploy this application. What options do I have? Compare them by
    cost, complexity and how well they fit a single container + Postgres.

    # Prompt 2: deploy as code
    Deploy this application to AWS using [CloudFormation | CDK | Terraform].
    Keep secrets (DB password, token secret) out of the template — use
    Secrets Manager or SSM Parameter Store.

    # Prompt 3:
    Give me the URL.

    # Prompt 4: HTTPS without buying a domain
    Are there any options to use HTTPS without buying a domain?
    (Typical answer: put CloudFront in front — you get a *.cloudfront.net URL with TLS.)

    # Prompt 5: least privilege
    Create a deploy role for CI with the least permissions it needs to deploy
    this stack — nothing extra. Use GitHub OIDC instead of long-lived keys.

    # Prompt 6: CI/CD
    Create a CI/CD pipeline (GitHub Actions) that:
    - runs backend and frontend tests in parallel
    - builds the Docker Compose stack and runs integration and e2e tests against it
    - deploys only when everything is green, on pushes to main

```mermaid
flowchart LR
    push([git push]) --> be[Backend tests]
    push --> fe[Frontend tests]
    be --> stack[Compose stack:<br/>integration + e2e]
    fe --> stack
    stack --> build[Build & push image]
    build --> dep[Deploy to dev]
    dep --> smoke[Smoke test /health]
```

**Done when:** a push to `main` ends with the new version live, and a failing test stops the deploy.

### 7. Clean up

Delete what you don't use, to avoid paying for it:

    aws cloudformation delete-stack --stack-name [STACK_NAME]
    aws cloudformation wait stack-delete-complete --stack-name [STACK_NAME]

> 💡 Also check for leftovers that stacks don't own: ECR images, log groups, snapshots, S3 buckets with `Retain` policies.

---

## Module 4: Environments, Observability & Operations

### 1. Dev and prod environments

**Goal:** two isolated environments from the same templates, so you can test before users see a change.

```mermaid
flowchart LR
    commit([commit on main]) --> ci[CI: test + build once]
    ci --> img[(ECR<br/>20261005-142233-a1b2c3d)]
    img --> dev[Dev env<br/>auto-deploy]
    dev --> check{Verified in dev?}
    check -- yes, manual approval --> prod[Prod env<br/>same image tag]
    check -- no --> fix[Fix & push again]
```

    # Prompt 1: second environment
    Create a second, independent copy of our deployment infrastructure for a
    production environment. It must run alongside the existing one with its
    own database and compute. Parameterize the templates by environment name
    instead of duplicating them.

    The current environment becomes dev; CI/CD deploys to dev on every push.
    Prod gets its own URL and is deployed only by an explicit promotion step.

    Document clearly which stack/URL is dev and which is prod (e.g. in
    deploy/README.md, plus a parent stack or a table that lists both).

    # Prompt 2: build once, promote the same image
    Use Amazon ECR as the image registry. CI builds the image once, tags it,
    pushes it, and deploys it to dev. Promoting to prod never rebuilds: it
    deploys the exact tag that is running in dev, so what was tested is what ships.

    Tag format: YYYYMMDD-HHMMSS-<git-sha>, e.g. 20260813-163457-83242da

For larger production workloads consider managed services:

| Need | Options |
|---|---|
| Container orchestration | ECS/Fargate, EKS, Cloud Run |
| Managed Postgres | RDS / Aurora, Neon, Supabase |
| Secrets | Secrets Manager, SSM Parameter Store |
| CDN / TLS / WAF | CloudFront + ACM + AWS WAF |

### 2. Observability: OpenTelemetry

**Goal:** the app reports what it's doing, in a vendor-neutral format.

The three signals:

| Signal | Answers | Example |
|---|---|---|
| **Metrics** | *Is something wrong?* | request rate, error rate, p95 latency, business counters |
| **Traces** | *Where is it wrong?* | one request through API → DB → external call |
| **Logs** | *Why is it wrong?* | exception with stack trace, correlated by trace id |

    Instrument the FastAPI backend with OpenTelemetry.

    Export traces, metrics and logs with OTLP (no collector yet). Include
    resource attributes: service.name, deployment.environment and the
    deployed git commit. Put the trace id in every log line.

### 3. OTel Collector and the observability stack

```mermaid
flowchart LR
    app[App<br/>OTel SDK] -- OTLP --> col[OTel Collector]
    col -- metrics --> prom[Prometheus]
    col -- logs --> loki[Loki]
    col -- traces --> tempo[Tempo]
    prom --> graf[Grafana]
    loki --> graf
    tempo --> graf
    prom -- rules --> am[Alerts]
```

    # Prompt 1:
    Add an OpenTelemetry Collector.

    Create an observability/ directory with Docker Compose for:
    - OpenTelemetry Collector
    - Prometheus
    - Loki
    - Tempo
    - Grafana (with all three provisioned as data sources)

    Keep it a separate Compose project from the application stack.

    # Prompt 2: business metrics + dashboard
    I want to perform an action in the app and see it on a dashboard. Add
    metrics for: [how many DOMAIN_ENTITY are created], [how many users are
    active right now], [how many ITEMS are created inside a DOMAIN_ENTITY].
    Add a provisioned Grafana dashboard with these plus the RED metrics
    (Rate, Errors, Duration) for every endpoint.

**Done when:** you click through the app and watch the numbers move in Grafana, and a slow request can be opened as a trace.

### 4. Deploy the observability stack

    Deploy the observability stack to the cloud. It must be separate from the
    application stacks. Connect both dev and prod to it, and make sure every
    signal carries the environment so dashboards can filter by it.
    Grafana must not be publicly open without authentication.

### 5. Alerting

**Goal:** be told about problems before users report them — and prove the alerts actually fire.

Start with alerts on symptoms users feel:

| Alert | Example condition |
|---|---|
| High error rate | 5xx ratio > 5% for 5 min |
| High latency | p95 > 1s for 10 min |
| Service down | no successful scrape / health check for 2 min |
| Business anomaly | create-[ITEM] failure ratio > X% |

    Create Prometheus alert rules for error rate, latency, availability and
    [business metric]. Each rule gets a severity, a summary and a runbook note.

Then **test the alerting** with a deliberate, controllable fault:

    I want to test that alerting works. Add a fault-injection flag (env var,
    off by default) that makes [an operation, e.g. creating an ITEM] fail a
    configurable percentage of the time — in a way unit tests would not catch.
    Turn it on in dev, confirm the alert fires, turn it off, confirm it resolves.

### 6. On-call agent

**Goal:** a first responder that investigates alerts and proposes a fix while you sleep — with a human still approving.

```mermaid
sequenceDiagram
    participant P as Prometheus
    participant W as Watcher script
    participant A as Coding agent (headless)
    participant G as Git / CI
    participant H as Human on-call
    W->>P: poll /api/v1/alerts
    P-->>W: alert FIRING
    W->>A: start session with alert + logs + traces
    A->>A: reproduce, find root cause
    A->>G: commit fix on a new branch, open PR
    G-->>H: CI results + PR to review
    H->>G: approve & merge → deploy
```

    Build an on-call agent in ops/alert-agent/: a script that polls Prometheus
    for firing alerts. When one fires, it gathers evidence (alert labels, recent
    error logs from Loki, a failing trace from Tempo) and starts a headless
    coding-agent session (e.g. `claude -p`) on a fresh branch to find the root
    cause and fix it with a test.

    Guardrails:
    - never push to main or deploy; open a PR for a human to review
    - one session per alert (deduplicate), with a timeout and a budget
    - restricted tool permissions; read-only cloud credentials
    - if it changes nothing, delete the branch and report its findings

---

## Appendix A: Production readiness checklist

**Code & tests**
- [ ] Unit tests for backend and frontend, run in CI
- [ ] Integration + E2E tests against the full stack
- [ ] Linting / formatting enforced in CI

**Security**
- [ ] No secrets in git; config from env vars / secret manager
- [ ] Passwords hashed; tokens expire
- [ ] HTTPS everywhere; CORS restricted to known origins
- [ ] Containers run as non-root; dependencies scanned
- [ ] CI and agents use least-privilege roles (OIDC, no long-lived keys)

**Delivery**
- [ ] Infrastructure as code; no manual console changes
- [ ] Build once, promote the same image dev → prod
- [ ] Database migrations versioned and run on deploy
- [ ] Rollback is one command (redeploy previous tag)

**Operations**
- [ ] `/health` endpoint used by load balancer and deploy checks
- [ ] Metrics, traces and logs with environment + version labels
- [ ] Dashboards for RED metrics and business metrics
- [ ] Alerts tested with fault injection, each with a runbook
- [ ] Backups enabled and a restore tested at least once
- [ ] Budget / spend alerts in the cloud account; unused resources cleaned up

## Appendix B: Prompt patterns that work

| Pattern | Example |
|---|---|
| **Ask before doing** | "What options do I have? Compare them before implementing." |
| **Propose then implement** | "What scenarios should we test? List them, then implement." |
| **Constrain the output** | "Put it in `e2e/`, add a `make e2e` target." |
| **Give the contract** | "Implement `openapi.yaml`" instead of "build a backend for this frontend". |
| **Define done** | "…and make sure `make test` passes." |
| **Paste the evidence** | Paste the full error/log, not a description of it. |
| **Lock in lessons** | "Add this rule to CLAUDE.md so you don't do it again." |

## Further reading

- DataTalksClub — AI Dev Tools Zoomcamp (source of the original prompts): https://github.com/DataTalksClub/ai-dev-tools-zoomcamp
- The Twelve-Factor App: https://12factor.net
- OpenAPI Specification: https://spec.openapis.org/oas/latest.html
- OpenTelemetry documentation: https://opentelemetry.io/docs/
- Google SRE Book — Monitoring Distributed Systems: https://sre.google/sre-book/monitoring-distributed-systems/
- AWS Well-Architected Framework: https://aws.amazon.com/architecture/well-architected/
- Playwright documentation: https://playwright.dev
- Claude Code best practices: https://www.anthropic.com/engineering/claude-code-best-practices
