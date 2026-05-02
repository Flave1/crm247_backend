import { randomUUID } from "node:crypto";
import { Router } from "express";
import { ObjectId } from "mongodb";
import { z } from "zod";
import { config } from "../config.js";
import { getMongoDb } from "../db/mongo.js";

export const emailsRouter = Router();

const metadataSchema = z.record(z.unknown()).default({});

const sendEmailSchema = z.object({
  domainId: z.string().min(1).max(120),
  contactId: z.string().optional().nullable(),
  to: z.string().email(),
  from: z.string().email().optional().nullable(),
  subject: z.string().min(1).max(240),
  html: z.string().min(1).max(100_000),
  text: z.string().max(20_000).optional().nullable(),
  metadata: metadataSchema
});

function nowIso() {
  return new Date().toISOString();
}

function normalizeEmail(email: string) {
  return email.trim().toLowerCase();
}

function objectIdFrom(value: string | null | undefined) {
  if (!value || !ObjectId.isValid(value)) return null;
  return new ObjectId(value);
}

function absoluteApiUrl(path: string) {
  return `${config.API_ORIGIN.replace(/\/$/, "")}${path}`;
}

function encodeRedirectUrl(url: string) {
  return encodeURIComponent(url);
}

function rewriteLinks(html: string, trackingId: string) {
  return html.replace(/href=(["'])(.*?)\1/gi, (match, quote: string, rawUrl: string) => {
    const url = rawUrl.trim();
    if (
      !url ||
      url.startsWith("#") ||
      url.startsWith("mailto:") ||
      url.startsWith("tel:") ||
      url.startsWith("javascript:")
    ) {
      return match;
    }

    const trackedUrl = absoluteApiUrl(
      `/email/click/${encodeURIComponent(trackingId)}?u=${encodeRedirectUrl(url)}`
    );
    return `href=${quote}${trackedUrl}${quote}`;
  });
}

function injectTrackingPixel(html: string, trackingId: string) {
  const pixelUrl = absoluteApiUrl(`/email/open/${encodeURIComponent(trackingId)}.gif`);
  const pixel = `<img src="${pixelUrl}" width="1" height="1" alt="" style="display:none!important;opacity:0;width:1px;height:1px;" />`;
  if (/<\/body>/i.test(html)) {
    return html.replace(/<\/body>/i, `${pixel}</body>`);
  }
  return `${html}${pixel}`;
}

async function upsertContactForEmail(params: {
  domainId: string;
  email: string;
  contactId?: string | null;
}) {
  const db = await getMongoDb();
  const timestamp = nowIso();
  const contactObjectId = objectIdFrom(params.contactId);
  const normalizedEmail = normalizeEmail(params.email);

  if (contactObjectId) {
    const existing = await db.collection("contacts").findOne({
      _id: contactObjectId,
      domainId: params.domainId
    });
    if (existing) return existing;
  }

  const contact = await db.collection("contacts").findOneAndUpdate(
    { domainId: params.domainId, email: normalizedEmail },
    {
      $setOnInsert: {
        domainId: params.domainId,
        email: normalizedEmail,
        isUnsubscribed: false,
        properties: {},
        createdAt: timestamp
      },
      $set: {
        updatedAt: timestamp
      }
    },
    { upsert: true, returnDocument: "after" }
  );

  return contact;
}

function transparentGif() {
  return Buffer.from(
    "R0lGODlhAQABAPAAAP///wAAACH5BAAAAAAALAAAAAABAAEAAAICRAEAOw==",
    "base64"
  );
}

emailsRouter.post("/emails/send", async (req, res) => {
  const parsed = sendEmailSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ ok: false, error: parsed.error.flatten() });
    return;
  }

  const db = await getMongoDb();
  const body = parsed.data;
  const timestamp = nowIso();
  const contact = await upsertContactForEmail({
    domainId: body.domainId,
    email: body.to,
    contactId: body.contactId
  });
  if (!contact) {
    res.status(500).json({ ok: false, error: "Unable to create or load contact" });
    return;
  }

  const contactId = contact?._id?.toString() || null;
  const trackingId = `em_${randomUUID()}`;
  const rewrittenHtml = rewriteLinks(body.html, trackingId);
  const trackedHtml = injectTrackingPixel(rewrittenHtml, trackingId);
  const message = {
    domainId: body.domainId,
    contactId,
    trackingId,
    provider: config.EMAIL_PROVIDER,
    status: "sent",
    from: normalizeEmail(body.from || config.EMAIL_FROM),
    to: normalizeEmail(body.to),
    subject: body.subject,
    html: body.html,
    trackedHtml,
    text: body.text || null,
    metadata: body.metadata,
    openCount: 0,
    clickCount: 0,
    lastOpenedAt: null,
    lastClickedAt: null,
    createdAt: timestamp,
    sentAt: timestamp,
    updatedAt: timestamp
  };

  const insertResult = await db.collection("outbound_messages").insertOne(message);

  await db.collection("contacts").updateOne(
    { _id: contact._id },
    {
      $set: {
        updatedAt: timestamp,
        lastEmailSentAt: timestamp,
        lastEmailSubject: body.subject
      },
      $inc: {
        emailSentCount: 1
      }
    }
  );

  await db.collection("email_events").insertOne({
    domainId: body.domainId,
    contactId,
    messageId: insertResult.insertedId.toString(),
    trackingId,
    eventType: "sent",
    subject: body.subject,
    targetUrl: null,
    userAgent: req.get("user-agent") || null,
    ip: req.ip || null,
    metadata: body.metadata,
    timestamp,
    createdAt: timestamp
  });

  res.status(201).json({
    ok: true,
    message: {
      id: insertResult.insertedId.toString(),
      contactId,
      trackingId,
      status: message.status,
      provider: message.provider,
      to: message.to,
      subject: message.subject,
      openUrl: absoluteApiUrl(`/email/open/${encodeURIComponent(trackingId)}.gif`),
      previewHtml: trackedHtml
    }
  });
});

emailsRouter.get("/email/open/:trackingId", async (req, res) => {
  const trackingId = String(req.params.trackingId || "").replace(/\.gif$/i, "");
  const db = await getMongoDb();
  const timestamp = nowIso();
  const message = await db.collection("outbound_messages").findOne({ trackingId });

  if (message) {
    await db.collection("email_events").insertOne({
      domainId: message.domainId,
      contactId: message.contactId || null,
      messageId: message._id?.toString(),
      trackingId,
      eventType: "open",
      subject: message.subject,
      targetUrl: null,
      userAgent: req.get("user-agent") || null,
      ip: req.ip || null,
      metadata: {},
      timestamp,
      createdAt: timestamp
    });

    await db.collection("outbound_messages").updateOne(
      { _id: message._id },
      {
        $set: { updatedAt: timestamp, lastOpenedAt: timestamp },
        $inc: { openCount: 1 }
      }
    );

    if (message.contactId && ObjectId.isValid(message.contactId)) {
      await db.collection("contacts").updateOne(
        { _id: new ObjectId(message.contactId) },
        {
          $set: { updatedAt: timestamp, lastEmailOpenedAt: timestamp },
          $inc: { emailOpenCount: 1 }
        }
      );
    }
  }

  res.setHeader("Content-Type", "image/gif");
  res.setHeader("Cache-Control", "no-store, no-cache, must-revalidate, proxy-revalidate");
  res.send(transparentGif());
});

emailsRouter.get("/email/click/:trackingId", async (req, res) => {
  const trackingId = String(req.params.trackingId || "").trim();
  const targetUrl = String(req.query.u || "").trim();
  const redirectUrl = targetUrl || config.WEB_ORIGIN;
  const db = await getMongoDb();
  const timestamp = nowIso();
  const message = await db.collection("outbound_messages").findOne({ trackingId });

  if (message) {
    await db.collection("email_events").insertOne({
      domainId: message.domainId,
      contactId: message.contactId || null,
      messageId: message._id?.toString(),
      trackingId,
      eventType: "click",
      subject: message.subject,
      targetUrl: redirectUrl,
      userAgent: req.get("user-agent") || null,
      ip: req.ip || null,
      metadata: {},
      timestamp,
      createdAt: timestamp
    });

    await db.collection("outbound_messages").updateOne(
      { _id: message._id },
      {
        $set: { updatedAt: timestamp, lastClickedAt: timestamp },
        $inc: { clickCount: 1 }
      }
    );

    if (message.contactId && ObjectId.isValid(message.contactId)) {
      await db.collection("contacts").updateOne(
        { _id: new ObjectId(message.contactId) },
        {
          $set: { updatedAt: timestamp, lastEmailClickedAt: timestamp },
          $inc: { emailClickCount: 1 }
        }
      );
    }
  }

  res.redirect(302, redirectUrl);
});

emailsRouter.get("/emails/messages", async (req, res) => {
  const db = await getMongoDb();
  const domainId = String(req.query.domainId || "").trim();
  const contactId = String(req.query.contactId || "").trim();
  const query: Record<string, string> = {};
  if (domainId) query.domainId = domainId;
  if (contactId) query.contactId = contactId;

  const messages = await db
    .collection("outbound_messages")
    .find(query)
    .project({ html: 0, trackedHtml: 0 })
    .sort({ createdAt: -1 })
    .limit(100)
    .toArray();

  res.json({ ok: true, messages });
});

emailsRouter.get("/emails/events", async (req, res) => {
  const db = await getMongoDb();
  const domainId = String(req.query.domainId || "").trim();
  const contactId = String(req.query.contactId || "").trim();
  const query: Record<string, string> = {};
  if (domainId) query.domainId = domainId;
  if (contactId) query.contactId = contactId;

  const events = await db
    .collection("email_events")
    .find(query)
    .sort({ timestamp: -1 })
    .limit(100)
    .toArray();

  res.json({ ok: true, events });
});
