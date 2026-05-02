# crm247 Build Phases

## Phase 1: Foundation

Goal: create a clean project base.

Deliverables:

- monorepo structure
- backend API app
- frontend dashboard shell
- MongoDB Atlas connection helper
- shared types
- environment template

## Phase 2: Cookie Tracking

Goal: capture anonymous visitor activity.

Status: **implemented**

Built:

- `GET /tracker/:domainId.js`
- `POST /track/visitor`
- `POST /track/events/batch`
- `POST /track/identify`
- `GET /track/visitors`
- `GET /track/events`
- first-party cookie `eg_visitor_id`
- session ID in localStorage
- page view, click, form submit, time on page, exit intent
- demo UI that loads the tracker and fires events

MongoDB collections:

- `visitors`
- `visitor_events`

## Phase 3: Contact Identity

Goal: link anonymous visitors to contacts.

Status: **implemented**

Built:

- email normalization
- contact upsert
- visitor-to-contact linking
- contact activity timeline
- contact list endpoint
- contact update endpoint
- dashboard contact activity panel

MongoDB collections:

- `contacts`
- update `visitors.contactId`

## Phase 4: Email Tracking

Goal: track outbound email engagement.

Build:

- `POST /emails/send`
- `GET /email/open/:trackingId`
- `GET /email/click/:trackingId`
- link rewriting
- tracking pixel injection

MongoDB collections:

- `outbound_messages`
- `email_events`

## Phase 5: LangGraph Multi-Agent Workflow

Goal: coordinate specialist agents for engagement decisions.

Agents:

- Supervisor Agent
- Signal Ingestion Agent
- Identity Agent
- Intent Analyst Agent
- Retrieval Agent
- Strategy Agent
- Message Agent
- Policy Agent
- Delivery Agent
- Learning Agent

MongoDB collections:

- `engagement_runs`
- `engagement_queue`
- `agent_tasks`
- `agent_messages`
- `agent_decision_traces`
- `langgraph_checkpoints`
- `langgraph_checkpoint_writes`

## Phase 6: Intent Scoring and Policy

Goal: deterministic scoring plus AI reasoning.

Rules:

- product page view: +10
- pricing or checkout page: +20
- CTA click: +20
- form submit: +35
- email open: +8
- email click: +20
- bounce or unsubscribe: hard stop

Autonomy modes:

- `assisted`: draft only
- `guardrailed`: queue for approval
- `full`: send if confidence and policy pass

## Phase 7: Dashboard and Demo Polish

Goal: make the agent system easy to judge.

Views:

- visitors
- contacts
- email events
- engagement queue
- decision trace
- message composer

## Phase 8: Atlas Retrieval and Learning

Goal: use MongoDB Atlas as adaptive agent memory.

Build:

- `agent_memories`
- optional vector index
- Retrieval Agent reads similar journeys and successful messages
- Learning Agent writes outcomes after opens/clicks
