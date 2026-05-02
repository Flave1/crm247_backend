import { randomUUID } from "node:crypto";
import { Router } from "express";
import { ObjectId } from "mongodb";
import { z } from "zod";
import { getMongoDb } from "../db/mongo.js";
import { buildTrackerScript } from "../tracker/script.js";

export const trackingRouter = Router();

const eventTypes = [
  "page_view",
  "click",
  "form_submit",
  "time_on_page",
  "exit_intent",
  "custom"
] as const;

const metadataSchema = z.record(z.unknown()).default({});

const visitorSchema = z.object({
  domainId: z.string().min(1).max(120),
  visitorId: z.string().min(1).max(160).optional(),
  sessionId: z.string().max(160).optional().nullable(),
  email: z.string().email().optional().nullable(),
  pageUrl: z.string().max(2048).optional().nullable(),
  pageTitle: z.string().max(500).optional().nullable(),
  referrer: z.string().max(2048).optional().nullable(),
  userAgent: z.string().max(1000).optional().nullable(),
  properties: metadataSchema
});

const identifySchema = z.object({
  domainId: z.string().min(1).max(120),
  visitorId: z.string().min(1).max(160),
  email: z.string().email(),
  properties: metadataSchema
});

const eventSchema = z.object({
  domainId: z.string().min(1).max(120),
  visitorId: z.string().min(1).max(160),
  sessionId: z.string().max(160).optional().nullable(),
  eventType: z.enum(eventTypes),
  pageUrl: z.string().min(1).max(2048),
  pageTitle: z.string().max(500).optional().nullable(),
  referrer: z.string().max(2048).optional().nullable(),
  metadata: metadataSchema,
  timestamp: z.string().optional().nullable()
});

const batchSchema = z.object({
  events: z.array(eventSchema).min(1).max(500)
});

function nowIso() {
  return new Date().toISOString();
}

function normalizeEmail(email: string | null | undefined) {
  const normalized = String(email || "").trim().toLowerCase();
  return normalized || null;
}

function safeTimestamp(value: string | null | undefined) {
  if (!value) return nowIso();
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return nowIso();
  return date.toISOString();
}

function activeMsDelta(metadata: Record<string, unknown>) {
  const raw = metadata.activeMsDelta ?? metadata.active_ms_delta;
  const parsed = Number(raw);
  if (!Number.isFinite(parsed) || parsed <= 0) return 0;
  return Math.min(Math.round(parsed), 60 * 60 * 1000);
}

async function upsertContact(params: {
  domainId: string;
  email: string;
  properties?: Record<string, unknown>;
  pageUrl?: string | null;
}) {
  const db = await getMongoDb();
  const timestamp = nowIso();
  const email = normalizeEmail(params.email);
  if (!email) return null;

  const result = await db.collection("contacts").findOneAndUpdate(
    { domainId: params.domainId, email },
    {
      $setOnInsert: {
        domainId: params.domainId,
        email,
        isUnsubscribed: false,
        createdAt: timestamp,
        properties: params.properties || {}
      },
      $set: {
        updatedAt: timestamp,
        lastWebsiteVisitAt: timestamp,
        ...(params.pageUrl ? { lastWebsitePageUrl: params.pageUrl } : {})
      }
    },
    { upsert: true, returnDocument: "after" }
  );
  return result;
}

async function linkVisitorToContact(params: {
  domainId: string;
  visitorId: string;
  email: string;
  properties?: Record<string, unknown>;
  pageUrl?: string | null;
}) {
  const db = await getMongoDb();
  const contact = await upsertContact({
    domainId: params.domainId,
    email: params.email,
    properties: params.properties,
    pageUrl: params.pageUrl
  });
  const contactId = contact?._id?.toString();
  await db.collection("visitors").updateOne(
    { domainId: params.domainId, visitorId: params.visitorId },
    {
      $set: {
        email: normalizeEmail(params.email),
        contactId,
        isIdentified: true,
        identifiedAt: nowIso(),
        updatedAt: nowIso()
      }
    }
  );
  return { contact, contactId };
}

trackingRouter.get("/tracker/:domainId.js", (req, res) => {
  const domainId = String(req.params.domainId || "").replace(/\.js$/i, "").trim();
  if (!domainId) {
    res.status(400).send("/* Missing domain id */");
    return;
  }
  res.setHeader("Content-Type", "application/javascript; charset=utf-8");
  res.setHeader("Cache-Control", "no-store");
  res.send(buildTrackerScript(domainId));
});

trackingRouter.post("/track/visitor", async (req, res) => {
  const parsed = visitorSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ ok: false, error: parsed.error.flatten() });
    return;
  }

  const db = await getMongoDb();
  const body = parsed.data;
  const timestamp = nowIso();
  const visitorId = body.visitorId || `v_${randomUUID()}`;
  const email = normalizeEmail(body.email);

  await db.collection("visitors").updateOne(
    { domainId: body.domainId, visitorId },
    {
      $setOnInsert: {
        domainId: body.domainId,
        visitorId,
        firstSeenAt: timestamp,
        pageViewCount: 0,
        sessionCount: 0,
        totalActiveMs: 0,
        sessionIds: []
      },
      $set: {
        lastSeenAt: timestamp,
        updatedAt: timestamp,
        lastPageUrl: body.pageUrl || null,
        lastPageTitle: body.pageTitle || null,
        referrer: body.referrer || null,
        userAgent: body.userAgent || null,
        isIdentified: Boolean(email),
        ...(email ? { email } : {})
      }
    },
    { upsert: true }
  );

  let contactId: string | undefined;
  if (email) {
    const linked = await linkVisitorToContact({
      domainId: body.domainId,
      visitorId,
      email,
      properties: body.properties,
      pageUrl: body.pageUrl
    });
    contactId = linked.contactId;
  }

  res.json({
    ok: true,
    visitorId,
    contactId,
    isIdentified: Boolean(email)
  });
});

trackingRouter.post("/track/identify", async (req, res) => {
  const parsed = identifySchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ ok: false, error: parsed.error.flatten() });
    return;
  }

  const body = parsed.data;
  const linked = await linkVisitorToContact({
    domainId: body.domainId,
    visitorId: body.visitorId,
    email: body.email,
    properties: body.properties
  });

  res.json({
    ok: true,
    visitorId: body.visitorId,
    contactId: linked.contactId,
    email: normalizeEmail(body.email)
  });
});

trackingRouter.post("/track/events/batch", async (req, res) => {
  const parsed = batchSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ ok: false, error: parsed.error.flatten() });
    return;
  }

  const db = await getMongoDb();
  const events = parsed.data.events;
  const createdAt = nowIso();
  const visitorCache = new Map<string, any>();
  const docs = [];

  for (const event of events) {
    const visitorKey = `${event.domainId}:${event.visitorId}`;
    let visitor = visitorCache.get(visitorKey);
    if (!visitor) {
      visitor = await db.collection("visitors").findOne({
        domainId: event.domainId,
        visitorId: event.visitorId
      });
      visitorCache.set(visitorKey, visitor);
    }

    if (!visitor) {
      await db.collection("visitors").updateOne(
        { domainId: event.domainId, visitorId: event.visitorId },
        {
          $setOnInsert: {
            domainId: event.domainId,
            visitorId: event.visitorId,
            firstSeenAt: createdAt,
            pageViewCount: 0,
            sessionCount: 0,
            totalActiveMs: 0,
            sessionIds: [],
            isIdentified: false
          },
          $set: {
            lastSeenAt: createdAt,
            updatedAt: createdAt
          }
        },
        { upsert: true }
      );
      visitor = await db.collection("visitors").findOne({
        domainId: event.domainId,
        visitorId: event.visitorId
      });
      visitorCache.set(visitorKey, visitor);
    }

    if (event.eventType === "form_submit") {
      const email = normalizeEmail(String(event.metadata.email || ""));
      if (email) {
        const linked = await linkVisitorToContact({
          domainId: event.domainId,
          visitorId: event.visitorId,
          email,
          properties: event.metadata,
          pageUrl: event.pageUrl
        });
        visitor = {
          ...visitor,
          contactId: linked.contactId,
          email,
          isIdentified: true
        };
        visitorCache.set(visitorKey, visitor);
      }
    }

    const timestamp = safeTimestamp(event.timestamp);
    const update: Record<string, unknown> = {
      $set: {
        lastSeenAt: timestamp,
        updatedAt: createdAt,
        lastPageUrl: event.pageUrl,
        lastPageTitle: event.pageTitle || null
      }
    };

    const inc: Record<string, number> = {};
    if (event.eventType === "page_view") inc.pageViewCount = 1;
    if (event.eventType === "time_on_page") inc.totalActiveMs = activeMsDelta(event.metadata);
    if (Object.keys(inc).length > 0) update.$inc = inc;
    const knownSessions = Array.isArray(visitor?.sessionIds) ? visitor.sessionIds : [];
    if (event.sessionId && !knownSessions.includes(event.sessionId)) {
      update.$addToSet = { sessionIds: event.sessionId };
      update.$inc = { ...(update.$inc as Record<string, number> | undefined), sessionCount: 1 };
      if (visitor) {
        visitor.sessionIds = [...(visitor.sessionIds || []), event.sessionId];
        visitorCache.set(visitorKey, visitor);
      }
    }

    await db.collection("visitors").updateOne(
      { domainId: event.domainId, visitorId: event.visitorId },
      update
    );

    if (visitor?.contactId) {
      const contactSet: Record<string, unknown> = {
        updatedAt: createdAt,
        lastWebsiteVisitAt: timestamp,
        lastWebsitePageUrl: event.pageUrl,
        lastWebsitePageTitle: event.pageTitle || null
      };
      const contactInc: Record<string, number> = {};
      if (event.eventType === "page_view") contactInc.pageViewCount = 1;
      if (event.eventType === "time_on_page") contactInc.totalActiveMs = activeMsDelta(event.metadata);
      if (event.sessionId && !knownSessions.includes(event.sessionId)) contactInc.sessionCount = 1;

      if (typeof visitor.contactId === "string" && ObjectId.isValid(visitor.contactId)) {
        await db.collection("contacts").updateOne(
          { _id: new ObjectId(visitor.contactId), domainId: event.domainId },
          {
            $set: contactSet,
            ...(Object.keys(contactInc).length > 0 ? { $inc: contactInc } : {})
          }
        );
      } else if (visitor.email) {
        await db.collection("contacts").updateOne(
          { domainId: event.domainId, email: visitor.email },
          {
            $set: contactSet,
            ...(Object.keys(contactInc).length > 0 ? { $inc: contactInc } : {})
          }
        );
      }
    }

    docs.push({
      domainId: event.domainId,
      visitorId: event.visitorId,
      contactId: visitor?.contactId || null,
      sessionId: event.sessionId || null,
      eventType: event.eventType,
      pageUrl: event.pageUrl,
      pageTitle: event.pageTitle || null,
      referrer: event.referrer || null,
      metadata: event.metadata,
      timestamp,
      createdAt
    });
  }

  if (docs.length > 0) {
    await db.collection("visitor_events").insertMany(docs, { ordered: false });
  }

  res.status(201).json({
    ok: true,
    accepted: events.length,
    created: docs.length
  });
});

trackingRouter.get("/track/visitors", async (req, res) => {
  const db = await getMongoDb();
  const domainId = String(req.query.domainId || "").trim();
  const query = domainId ? { domainId } : {};
  const visitors = await db
    .collection("visitors")
    .find(query)
    .sort({ lastSeenAt: -1 })
    .limit(50)
    .toArray();
  res.json({ ok: true, visitors });
});

trackingRouter.get("/track/events", async (req, res) => {
  const db = await getMongoDb();
  const domainId = String(req.query.domainId || "").trim();
  const visitorId = String(req.query.visitorId || "").trim();
  const query: Record<string, string> = {};
  if (domainId) query.domainId = domainId;
  if (visitorId) query.visitorId = visitorId;
  const events = await db
    .collection("visitor_events")
    .find(query)
    .sort({ timestamp: -1 })
    .limit(100)
    .toArray();
  res.json({ ok: true, events });
});
