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
    api/          Express + TypeScript backend
    web/          Vite + React frontend shell
  docs/
    BUILD_PHASES.md
  packages/
    shared/       Shared TypeScript types
```

## Phase 1 Status

Implemented foundation:

- clean monorepo layout
- backend health endpoint
- MongoDB Atlas connection helper
- frontend dashboard shell
- shared engagement types
- phase build plan

## Local Setup

Copy the env example:

```bash
cp .env.example .env
```

Install dependencies:

```bash
npm install
```

Run backend:

```bash
npm run dev:api
```

Run frontend:

```bash
npm run dev:web
```

## Core Future Flow

1. Demo site loads `/tracker/:domainId.js`.
2. Tracker creates `eg_visitor_id`.
3. Events are batched into MongoDB Atlas.
4. Visitor is identified when email is captured.
5. Email open/click events are recorded.
6. LangGraph agents analyze signals and create engagement queue items.
7. Dashboard shows queue, message draft, policy decision, and agent trace.

