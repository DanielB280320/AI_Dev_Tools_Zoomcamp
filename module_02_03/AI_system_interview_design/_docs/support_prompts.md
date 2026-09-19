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

### Context Engineering: AGENTS.md/CLAUDE.md

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

## Module 3:

### 1. Creating Dockerfile

    Create a Dockerfile that builds the frontend with Node, then builds a Python image with the backend and the frontend static files.

    Backend should serve the frontend.

### 2. Building Dockerfile

    So we have a Dockerfile I want to build this Dockerfile and I want to run it  so I want you to create a README file and put the instructions for running Dockerfile and building Dockerfile there in this README