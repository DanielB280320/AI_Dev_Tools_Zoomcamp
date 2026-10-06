# Build and Ship a Full-Stack App with AI Coding Assistants

## Module 2:

### 1. Start with a specification

    I want to build a system — I need your help with the specification. I want to build a system for interviewing: I'll send a link to candidates, and they'll need to do a system design interview.

    We need some special components. There will be a shared canvas that I can edit, and candidates can edit too — they can drag and drop components onto it and connect them with arrows. There should be common components like a queue, a database, and different rectangles for things like an LLM call (basically services), plus some other component types. In addition to the boxes and connections, we should also be able to do freeform drawing on the canvas.

    As the interviewer, I can create a link. Other people can then join using that link, and multiple people can join at the same time. Everyone should see updates in real time.

    Let's start with this — create me a specification.

### 2. Frontend First

    # Sample 1:
    Create a [project name] application. 

    [Paste the coding agent specification here.]

    Centralize every backend call in one services layer, and create a mock
    implementation of it so the whole app runs without a real backend

    Add tests.

    # Sample 2:
    So I want to create an application that would be the front end for this. I already want to start thinking about the backend, but right now I want you to just mock the calls to the backend — I'll implement the back end myself later.

### Move the Frontend into the Project

We can use the same following project structure:

    /backend     # backend application and its tests
    /docs        # supporting documentation
        /docs/spec.md
    /frontend    # frontend application
    AGENTS.md    # instructions for coding agents
    openapi.yaml # API agreement

To run a project you exported from Lovable:

    cd frontend
    npm i
    npm run dev

### 3. Context Engineering: AGENTS.md/CLAUDE.md

Create any of these files based on the coding agent you are using and as starting point you can add the following instructions: 

    for backend, use uv for dependency management. a few useful commands:

    uv sync
    uv add <PACKAGE-NAME>
    uv run python <PYTHON-FILE>

    regularly commit code to git 

### 4. OpenAPI Specifications

The specification is the agreement between frontend and backend. This specification gives explicit information about the endpoints, paths, request bodies, response bodies, and authentication rules:

    Read the frontend's API client in frontend/

    Create openapi.yaml at the repository root.

    Specify the backend this frontend expects: every endpoint, method, path, request body, response body, and which endpoints need authentication.

With this the backend gets a precise target instead of being inferred from frontend code. Not only we save tokens this way, but also get a clear picture of what exactly the backend needs.

### 5. The Backend

    Build a FastAPI backend in backend/ that implements the openapi.yaml spec.

    Use an in-memory store and seed it with data so the frontend has something to show. Add authentication with hashed passwords and bearer tokens for the endpoints that need it.

    Split the code into modules - routers, models, store, auth

    Write tests

### 6. Makefile 

Its suggested to create a Makefile to generate commands to run our app: 

    Create a Makefile so I can easily run the app.

### 7. Connecting Frontend and Backend

    Switch the frontend to use the real backend client. 

### 8. Database

    Replace the in-memory store with a database. Use SQLite and SQLAlchemy.
    Use an environment variable to configure which DB the server should connect to.
    Make it database-agnostic - later we will add support for other databases (e.g. Postgres).

---

## Module 3:

### 1. Creating Dockerfile

    Create a Dockerfile that builds the frontend with Node, then builds a Python image with the backend and the frontend static files.

    Backend should serve the frontend.

### 2. Building Dockerfile

    So we have a Dockerfile I want to build this Dockerfile and I want to run it so I want you to create a README file and put the instructions for running Dockerfile and building Dockerfile there in this README

### 3. Switch from SQLite to Postgres

To switch SQLite database to Postgres we can request the coding agent to create one pg database or do it manually wtih the command:

    docker run -d \
    --name interview-canvas-db \
    -e POSTGRES_USER=sdip \
    -e POSTGRES_PASSWORD=sdip \
    -e POSTGRES_DB=sdip \
    -p 5432:5432 \
    -v interview-canvas-pgdata:/var/lib/postgresql/data \
    postgres:16-alpine

    Add Postgres support to the backend.

    # When running the app from localhost we need to specify the db that will be use:
    export SDIP_DATABASE_URL=postgresql://sdip:sdip@localhost:5432/sdip

    # Run frontend and backend at the same time:
    make dev

### 4. Docker Compose

    Create docker-compose.yaml with two services: Postgres and the app.

### 5. Integration and end-to-end tests

    # Prompt 1:
    Create integration tests that run against docker-compose.yaml. What scenarios should we test?

    # Prompt 2:
    Add an end-to-end test that runs against docker-compose.yaml.

    Use Playwright to:

    1. Log in as the interviewer (session 1).
    2. Create an interview session.
    3. Share the join link.
    4. Join from a separate client as the candidate (session 2).
    5. Change the canvas as the candidate (session 2).
    6. Verify that the interviewer sees the change (session 1).

    Put the tests in the e2e/ folder in the repository root.

### 6. App deploying

When deploying the app to AWS we need to connect and give access to our coding agent to the cloud infrastructure:
    
    Set up Agent Toolkit for AWS by following instructions:
    https://raw.githubusercontent.com/aws/agent-toolkit-for-aws/refs/heads/main/setup-instructions/setup.md

    Your AWS Region is: us-east-2
    AWS experience: The new AWS experience

    # Prompt 1:
    Now I want to deploy the application builded what options I have

    # Prompt 2:
    Deploy this application to AWS. Use AWS CloudFormation.

    # Prompt 3:
    Now give me the url

    # Prompt 4:
    Are there any options to use https without buying a Domain?

    # Prompt 5: Limit the role permissions to deploy any change:
    I want to make sure that this role has the least amount of permissions it needs to do the deployment right so it doesn't have anything extra that it doesn't need

    # Prompt 6:
    Create a CI/CD pipeline that:

    - runs backend and frontend tests in parallel
    - builds the Docker Compose stack and runs integration and end-to-end tests against it

### 7. Clean up

    aws cloudformation delete-stack --stack-name sdip
    aws cloudformation wait stack-delete-complete --stack-name sdip

---

## Module 4:

### 1. Dev and prod environments

    # Prompt 1:
    Create a second, independent copy of our deployment infrastructure for a production environment. It should be able to run alongside the existing setup, with its own separate database and compute resources.
    The current environment will become the dev environment; Also whenever we push CI/CD will deploy to the dev environment by default
    URLs:
    Create a new URL using AWS CloudFormation to deploy the production App
    https://d1u9mpb2rc8ljk.cloudfront.net/ will point to the dev environment (the existing setup)

    Please document it so it's always clear where the dev is where prod is and maybe we can have like a 1 super stack that describes these two stacks or somehow it's clear what is where

    # Prompt 2:
    Image tagging and promotion strategy (ECR)

    We will use Amazon ECR as the image registry. In the CI/CD pipeline, the development deployment will build the Docker image once and push it to ECR. The development environment then pulls and runs that image.

    When we promote from development to production, we won't rebuild. Because we already know exactly which image version is running in development, production will pull and run that same image. This guarantees that what was tested in development is what runs in production.

    Version format: YYYYMMDD-HHMMSS-<git-sha>
    Example: 20260813-163457-83242da

In real production environments is suggested to use additional services like: 

    - Container Orchestration: ECS, ECR
    - Managed Databases Services: RDS, Neon

### 2. Observability and monitoring: OpenTelemetry

    Instrument the FastAPI backend with OpenTelemetry.

    Export traces and metrics with OTLP (no collector yet). Include service name, environment and deployed git commit

### 3. OTel Collectors:

    # Prompt 1:
    Add an OpenTelemetry Collector.

    Create "observability/" directory with Docker Compose for:

    - OpenTelemetry Collector
    - Prometheus
    - Loki
    - Tempo
    - Grafana

    Keep this as a separate Compose project from the application stack

    # Prompt 2: Collecting Telemetry
    So now I want to perform an action and I want to see this action to be reflected on the dashboard So let's track this metrics so I want to track how many interviews rooms we create, How many people are active in the interviews right now and also how many elements in the interview room we create

### 4. Deploy the observability stack:

    Deploy the observability stack. It should be separate from the application stack.
    Connect both development and production to it.

### 5. Alerting: 

    So what I want to do is now I want to test that our alerting system works So what I want to do is have a bug that will sleep into production so let's introduce a bug in such a way that it will affect some of our metrics metrics but it will not be caught by the test So what we can do is we can just let's say when somebody creates a component in the interview room sometimes it will not work can we do that I want to do this for testing

### 6. On-call Enginner: 

    I already want to prepare for an agent that is a script that is constantly checking the prometheus alerts When it sees that there is alert it starts a claude code session where it runs it in headless mode and figures out what the problem is and solves this problem

Source: DataTalksClub