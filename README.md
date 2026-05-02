# crm247

Multi-agent autonomous engagement platform for the MongoDB Agentic Evolution Hackathon.

## Goal

crm247 tracks website visitors with a first-party cookie, connects visitor behavior to email engagement, and uses a LangGraph multi-agent workflow to decide, draft, guardrail, and queue personalized outreach.

## Hackathon Theme

Primary theme: **Multi-Agent Collaboration**

MongoDB Atlas is used as:

- event store for website and email engagement
- shared agent context
- decision trace store
- queue state
- LangGraph checkpoint backend
- optional vector memory via Atlas Vector Search

## Project Structure

```txt
crm247/
  apps/
    api/          FastAPI + Python backend
    web/          Vite + React frontend shell
  docs/
    BUILD_PHASES.md
  packages/
    shared/       Shared TypeScript types
```

## Current Status

Implemented:

- clean monorepo layout
- backend health endpoint
- MongoDB Atlas connection helper
- frontend dashboard shell
- shared engagement types
- phase build plan
- generated website tracker script
- visitor registration endpoint
- batched website event ingestion
- visitor identify endpoint
- contacts API and contact activity timeline
- email send endpoint with tracking pixel injection
- email click redirect endpoint with link tracking
- email event feed and outbound message records
- demo UI that loads and exercises the tracker
- demo UI for identified contacts and linked website activity
- demo UI for creating and inspecting tracked emails
- phase 5 engagement runs with Aurray-shaped run, queue, and decision trace records
- deterministic LangGraph-style orchestration for multi-contact runs
- per-contact run state, claim-based processing, and queue execution workers
- retry and dead-letter handling for delivery failures
- in-app escalation records for approval, policy-held queue items, and permanent delivery failures, with Slack/Teams/SMS placeholders reserved

## Local Setup

Copy the env example:

```bash
cp .env.example .env
```

Install frontend dependencies:

```bash
npm install
```

Install backend dependencies:

```bash
python3 -m pip install -r apps/api/requirements.txt
```

Run backend:

```bash
npm run dev:api
```

Run frontend:

```bash
npm run dev:web
```

## Docker Compose

Run the backend API and MongoDB together:

```bash
docker compose up --build
```

The API will be available at `http://localhost:8080` and MongoDB at `mongodb://localhost:27017`.

To stop the stack:

```bash
docker compose down
```

## Core Flow

1. Demo site loads `/tracker/:domainId.js`.
2. Tracker creates `eg_visitor_id`.
3. Events are batched into MongoDB Atlas through `/track/events/batch`.
4. Visitor is identified when email is captured through `/track/identify`.
5. Contacts can be listed and inspected through `/contacts`.
6. Dashboard creates a tracked email through `/emails/send`.
7. Email opens hit `/email/open/:trackingId.gif`.
8. Email clicks redirect through `/email/click/:trackingId`.
9. Auto-engagement runs can enroll one or many contacts and process them in batches.
10. Queue workers send eligible items automatically in full-autonomy mode and retry transient failures.
11. Dashboard can inspect run contacts, queue items, policy decisions, traces, and notifications through the backend APIs.

## Phase 2 Endpoints

```txt
GET  /tracker/:domainId.js
POST /track/visitor
POST /track/events/batch
POST /track/identify
GET  /track/visitors
GET  /track/events
GET  /contacts
GET  /contacts/:contactId
PATCH /contacts/:contactId
GET  /contacts/:contactId/activity
POST /emails/send
GET  /emails/messages
GET  /emails/events
GET  /email/open/:trackingId.gif
GET  /email/click/:trackingId
POST /engagement/runs
GET  /engagement/runs
GET  /engagement/runs/:runId
PATCH /engagement/runs/:runId
GET  /engagement/runs/:runId/contacts
POST /engagement/runs/:runId/process
GET  /engagement/runs/:runId/queue
GET  /engagement/runs/:runId/queue/:queueItemId
POST /engagement/runs/:runId/queue/:queueItemId/approve
POST /engagement/runs/:runId/queue/:queueItemId/pause
POST /engagement/runs/:runId/queue/:queueItemId/generate-message
PUT  /engagement/runs/:runId/queue/:queueItemId/message
POST /engagement/queue/process
GET  /engagement/runs/:runId/decision-traces
GET  /engagement/runs/:runId/graph
GET  /engagement/runs/:runId/notifications
```
