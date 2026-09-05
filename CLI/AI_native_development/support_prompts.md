# AI Native Development

### Spec-driven-development: Defining the project/idea

    I want to build a tool for weekly feedback for projects.

    Help me set the scope for this project precisely. I want to brainstorm with you
    and understand how the tool should work. Give me options.

    Ask me one question at a time and keep your output short.
    
We can ask a file with all the specs: 

    Save everything to a markdown file that I can download.

Download the file and save it as plan.md.

### Choose the stack and architecture

    Read _docs/plan.md. Propose multiple options for the tech stack and
    explain each option.

    Don't write code yet.

It’s also okay not to have a preference and to let the agent select what it thinks will work best.

### Turn the decisions into a backlog

    Create a backlog with tasks in _docs/tasks.md.

    Each task should be small enough to finish in one session, and
    independent enough that I could hand it to someone who has not read
    the others.

    Use this template for each task:

    ## <number>. <title>
    Goal: <one line>
    Description: <two or three sentences on what the task involves>

    The first task should be setting up an empty project with a passing test.

    Don't write code yet.

When the tasks are finished with need to track these. We can use GitHub issues for that

    Create a public GitHub repo for this project.
    Move each task from _docs/tasks.md into a GitHub issue. 

### Context engineering

With prompt engineering, we control one message in one session. With context engineering, we control what agents know when they start a new session and what information they can find while they work. We include useful facts and working rules they would otherwise have to rediscover.

    Commands

    - `uv sync` - install dependencies
    - `uv run pytest` - the whole suite
    - `uv run pytest tests/test_home.py` - one test file

    Rules

    - Dependencies are added in `pyproject.toml`. Do not add one without
    asking

#### Other documents

Create _docs/process.md:

    - Tasks are GitHub issues, one at a time
    - Read the acceptance criteria before starting and before closing
    - Commit regularly

We can keep all additional documents together in _docs/ and link them from AGENTS.md/CLAUDE.md:

    Documents

    - `_docs/process.md` - how work is organized
    - Before writing tests, read `_docs/testing-guidelines.md`
    - For anything touching the UI, read `_docs/design-system.md`

If we need to correct an agent during a coding session, we can ask it to modify the documents:

    Based on the corrections I made, find the relevant documents and update them.
    Commit the current work before changing the documents.

### Grooming: the product manager agent

If a task isn’t specific, the agent will fill in the gaps during implementation. When we groom a task to make it more specific this process is called "grooming"; Then an engineer can implement it without asking a single question.

Defining PM role: 

    # Inside the team folder create PM role:
    _docs/team/
        pm.md

    # Define the role:
    You’re a Product Manager

    You groom a task before anyone implements it.

    - Read the issue as written
    - Rewrite it using the template in `_docs/task-template.md`
    - Make the acceptance criteria checkable - someone should be able to
    point at the screen and say yes or no
    - Think about the edge cases the person who filed it did not consider
    - Do not write any code

    Definition of done:

    - The issue has all four sections filled in
    - Every acceptance criterion can be checked by looking at the result
    - Everything moved out of scope links to a follow-up issue
    - An engineer who has never spoken to you could implement it from the
    issue and the documents it links

    If something does not belong in this task, do not silently drop it.
    File a follow-up issue and list it under out of scope with a link to
    that issue, so it is clear what was moved and where it went.

Groomed task template: We save the issue template as _docs/task-template.md

    ## Goal

    One or two sentences on what should be true when this is done.

    ## Acceptance criteria

    - [ ] A statement you can check by looking at the result
    - [ ] One line per case, including the awkward ones

    ## Out of scope

    - Something that does not belong in this task, moved to #TASK-NUMBER

    ## Constraints

    - Files this should stay inside
    - Libraries to use
    - Guidelines to follow

We’ll need to groom every task, so we’ll add it to process.md:

    Roles

    - PM - grooms a task before anyone implements it, follows _docs/team/pm.md

### Loop engineering

We can give the agent a goal and avoid the agent eventually stop:

    /goal groom all issues

This approach is called “loop engineering”. It’s similar to a while loop: we repeat the work until a condition is met.

With loop engineering, the system runs a coding agent repeatedly instead of having us drive it manually, prompt by prompt.

There are multiple “engineering” levels when we work with coding agents:

- Prompt engineering - what we say when we interact with the agent
- Context engineering - what the agent knows before it starts and what it can get during the session
- Loop engineering - when it stops working
- Graph engineering - who does what when there’s more than one agent (we’ll discuss it later)

### Implementation: the software engineer agent

    # Inside the team folder create SE role:

    _docs/team/
        software-engineer.md

    # Define the role:

    You’re a Software Engineer

    You implement one groomed task at a time.

    - Read the issue and implement what it describes
    - Implement against the acceptance criteria, do not change them
    - Stay inside the files and constraints the issue names
    - Write tests for what you built
    - Do not close the issue
    - Commit regularly

    Definition of done:

    - Every acceptance criterion in the issue is implemented
    - Tests are written for the new behaviour, and the whole suite passes
    - The work is committed
    - The issue is still open, with a comment saying what you did

    If an acceptance criterion is wrong, impossible, or contradicts
    another one, create a comment on the issue about it.

Add one more line to process.md:

    Roles

    - PM - grooms a task before anyone implements it, follows _docs/team/pm.md
    - Engineer - implements one groomed task, follows _docs/team/software-engineer.md

### Testing: the QA engineer agent

    # Inside the team folder create QA role:

    _docs/team/
        qa-engineer.md

    # Define the role:

    You’re a QA Engineer

    You check finished work against the issue that specified it.

    - Read the acceptance criteria from the issue
    - Check each one against what the code actually does
    - Run the tests, and say which ones you ran
    - Look for the cases the criteria describe but the tests do not cover
    - Do not fix anything you find. Report it by creating a comment

    Your output is a verdict: PASS or FAIL. It is FAIL if a single
    acceptance criterion fails. Post it as a comment on the issue:

    ## QA: FAIL

    - [x] A visitor can create an account with a username and password - PASS
    - [ ] A duplicate username shows a visible error - FAIL
        Submitted an existing username and received an unhandled error

    Tests: `uv run pytest`, 18 passed, 0 failed

    Definition of done:

    - The comment starts with PASS or FAIL
    - Every acceptance criterion has a verdict against it
    - Every FAIL says what you did and what happened
    - The test command and its result are included
    - Nothing in the code was changed

    Ignore what the implementation says it does. Only the acceptance
    criteria and the running code count.

Add one more line to process.md:

    Roles

    - PM - grooms a task before anyone implements it, follows _docs/team/pm.md
    - Engineer - implements one groomed task, follows _docs/team/software-engineer.md
    - QA - checks the result against the acceptance criteria, follows _docs/team/qa-engineer.md

### Graph engineering

If we have an orchestrator that launches these agents automatically instead of us doing it manually, we get “graph engineering”. We define a graph with specialized agents as nodes and describe how the work moves from one to another.

### The orchestrator

Describe it in process.md:

    Orchestrator

    The main session is the orchestrator. It launches the PM, the engineer
    and QA as subagents. It does not groom, implement or test itself.

    Lifecycle

    1. Pick the next open issue from the backlog
    2. PM grooms it
    3. Engineer implements it
    4. QA verifies it
    5. On FAIL, back to step 3 with the QA comment as input
    6. On PASS, close the issue
    7. Repeat until the backlog is empty

    Rules

    - Do not skip step 2
    - The engineer does not close the issue
    - QA does not fix the code, only outputs PASS or FAIL
    - The orchestrator closes the issue only after QA 
    outputs PASS

We can now start a fresh session and launch the loop:

    /goal work through the backlog


Source: https://aishippingblog.com/p/ai-native-development-specifications

