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

## Core Flow

1. Demo site loads `/tracker/:domainId.js`.
2. Tracker creates `eg_visitor_id`.
3. Events are batched into MongoDB Atlas through `/track/events/batch`.
4. Visitor is identified when email is captured through `/track/identify`.
5. Contacts can be listed and inspected through `/contacts`.
6. Dashboard creates a tracked email through `/emails/send`.
7. Email opens hit `/email/open/:trackingId.gif`.
8. Email clicks redirect through `/email/click/:trackingId`.
9. LangGraph agents analyze signals and create engagement queue items in a later phase.
10. Dashboard shows queue, message draft, policy decision, and agent trace in a later phase.

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
```
