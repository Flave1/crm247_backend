import { Router } from "express";
import { ObjectId } from "mongodb";
import { z } from "zod";
import { getMongoDb } from "../db/mongo.js";

export const contactsRouter = Router();

const updateContactSchema = z.object({
  firstName: z.string().max(120).optional().nullable(),
  lastName: z.string().max(120).optional().nullable(),
  company: z.string().max(180).optional().nullable(),
  properties: z.record(z.unknown()).optional()
});

function objectIdFrom(value: string) {
  if (!ObjectId.isValid(value)) return null;
  return new ObjectId(value);
}

function publicContact(contact: any) {
  return {
    id: contact._id?.toString(),
    domainId: contact.domainId,
    email: contact.email,
    firstName: contact.firstName || null,
    lastName: contact.lastName || null,
    company: contact.company || null,
    isUnsubscribed: Boolean(contact.isUnsubscribed),
    properties: contact.properties || {},
    createdAt: contact.createdAt,
    updatedAt: contact.updatedAt,
    lastWebsiteVisitAt: contact.lastWebsiteVisitAt || null,
    pageViewCount: contact.pageViewCount || 0,
    sessionCount: contact.sessionCount || 0
  };
}

contactsRouter.get("/contacts", async (req, res) => {
  const db = await getMongoDb();
  const domainId = String(req.query.domainId || "").trim();
  const search = String(req.query.search || "").trim();
  const query: Record<string, unknown> = {};

  if (domainId) query.domainId = domainId;
  if (search) {
    query.$or = [
      { email: { $regex: search, $options: "i" } },
      { firstName: { $regex: search, $options: "i" } },
      { lastName: { $regex: search, $options: "i" } },
      { company: { $regex: search, $options: "i" } }
    ];
  }

  const contacts = await db
    .collection("contacts")
    .find(query)
    .sort({ updatedAt: -1 })
    .limit(100)
    .toArray();

  res.json({ ok: true, contacts: contacts.map(publicContact) });
});

contactsRouter.get("/contacts/:contactId", async (req, res) => {
  const db = await getMongoDb();
  const contactObjectId = objectIdFrom(String(req.params.contactId || ""));
  if (!contactObjectId) {
    res.status(400).json({ ok: false, error: "Invalid contact id" });
    return;
  }

  const contact = await db.collection("contacts").findOne({ _id: contactObjectId });
  if (!contact) {
    res.status(404).json({ ok: false, error: "Contact not found" });
    return;
  }

  res.json({ ok: true, contact: publicContact(contact) });
});

contactsRouter.patch("/contacts/:contactId", async (req, res) => {
  const db = await getMongoDb();
  const contactObjectId = objectIdFrom(String(req.params.contactId || ""));
  if (!contactObjectId) {
    res.status(400).json({ ok: false, error: "Invalid contact id" });
    return;
  }

  const parsed = updateContactSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ ok: false, error: parsed.error.flatten() });
    return;
  }

  const body = parsed.data;
  const set: Record<string, unknown> = {
    updatedAt: new Date().toISOString()
  };
  if ("firstName" in body) set.firstName = body.firstName || null;
  if ("lastName" in body) set.lastName = body.lastName || null;
  if ("company" in body) set.company = body.company || null;

  const update: Record<string, unknown> = { $set: set };
  if (body.properties) {
    for (const [key, value] of Object.entries(body.properties)) {
      set[`properties.${key}`] = value;
    }
  }

  const contact = await db.collection("contacts").findOneAndUpdate(
    { _id: contactObjectId },
    update,
    { returnDocument: "after" }
  );

  if (!contact) {
    res.status(404).json({ ok: false, error: "Contact not found" });
    return;
  }

  res.json({ ok: true, contact: publicContact(contact) });
});

contactsRouter.get("/contacts/:contactId/activity", async (req, res) => {
  const db = await getMongoDb();
  const contactObjectId = objectIdFrom(String(req.params.contactId || ""));
  if (!contactObjectId) {
    res.status(400).json({ ok: false, error: "Invalid contact id" });
    return;
  }

  const contact = await db.collection("contacts").findOne({ _id: contactObjectId });
  if (!contact) {
    res.status(404).json({ ok: false, error: "Contact not found" });
    return;
  }

  const contactId = contact._id.toString();
  const visitors = await db
    .collection("visitors")
    .find({ contactId })
    .sort({ lastSeenAt: -1 })
    .toArray();
  const visitorIds = visitors.map((visitor) => visitor.visitorId).filter(Boolean);

  const eventQuery =
    visitorIds.length > 0
      ? {
          domainId: contact.domainId,
          $or: [{ contactId }, { visitorId: { $in: visitorIds } }]
        }
      : { domainId: contact.domainId, contactId };

  const websiteEvents = await db
    .collection("visitor_events")
    .find(eventQuery)
    .sort({ timestamp: -1 })
    .limit(200)
    .toArray();

  const emailEvents = await db
    .collection("email_events")
    .find({ domainId: contact.domainId, contactId })
    .sort({ timestamp: -1 })
    .limit(100)
    .toArray();

  const pageCounts = new Map<string, { pageUrl: string; pageTitle: string | null; count: number }>();
  for (const event of websiteEvents) {
    if (event.eventType !== "page_view") continue;
    const key = String(event.pageUrl || "");
    if (!key) continue;
    const existing = pageCounts.get(key) || {
      pageUrl: key,
      pageTitle: event.pageTitle || null,
      count: 0
    };
    existing.count += 1;
    pageCounts.set(key, existing);
  }

  const timeline = [
    ...websiteEvents.map((event) => ({
      id: event._id?.toString(),
      source: "website",
      type: event.eventType,
      visitorId: event.visitorId,
      sessionId: event.sessionId || null,
      pageUrl: event.pageUrl,
      pageTitle: event.pageTitle || null,
      subject: null,
      targetUrl: null,
      metadata: event.metadata || {},
      timestamp: event.timestamp
    })),
    ...emailEvents.map((event) => ({
      id: event._id?.toString(),
      source: "email",
      type: event.eventType,
      visitorId: null,
      sessionId: null,
      pageUrl: null,
      pageTitle: null,
      subject: event.subject || null,
      targetUrl: event.targetUrl || null,
      metadata: event.metadata || {},
      timestamp: event.timestamp
    }))
  ].sort((a, b) => String(b.timestamp).localeCompare(String(a.timestamp)));

  res.json({
    ok: true,
    contact: publicContact(contact),
    visitors: visitors.map((visitor) => ({
      id: visitor._id?.toString(),
      visitorId: visitor.visitorId,
      firstSeenAt: visitor.firstSeenAt,
      lastSeenAt: visitor.lastSeenAt,
      pageViewCount: visitor.pageViewCount || 0,
      sessionCount: visitor.sessionCount || 0,
      totalActiveMs: visitor.totalActiveMs || 0
    })),
    summary: {
      websiteEventCount: websiteEvents.length,
      emailEventCount: emailEvents.length,
      visitorCount: visitors.length,
      topPages: Array.from(pageCounts.values()).sort((a, b) => b.count - a.count).slice(0, 5)
    },
    timeline
  });
});
