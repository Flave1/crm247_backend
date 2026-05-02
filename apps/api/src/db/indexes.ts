import type { Db } from "mongodb";

export async function ensureIndexes(db: Db): Promise<void> {
  await Promise.all([
    db.collection("visitors").createIndex({ domainId: 1, visitorId: 1 }, { unique: true }),
    db.collection("visitor_events").createIndex({ visitorId: 1, timestamp: -1 }),
    db.collection("visitor_events").createIndex({ domainId: 1, timestamp: -1 }),
    db.collection("contacts").createIndex({ email: 1 }, { unique: true }),
    db.collection("contacts").createIndex({ domainId: 1, updatedAt: -1 }),
    db.collection("email_events").createIndex({ contactId: 1, timestamp: -1 }),
    db.collection("engagement_runs").createIndex({ status: 1, createdAt: -1 }),
    db.collection("engagement_queue").createIndex({ status: 1, nextRunAt: 1 }),
    db.collection("agent_decision_traces").createIndex({ runId: 1, contactId: 1, createdAt: -1 }),
    db.collection("outbound_messages").createIndex({ contactId: 1, createdAt: -1 })
  ]);
}

