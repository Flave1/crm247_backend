import { Router } from "express";

export const rootRouter = Router();

rootRouter.get("/", (_req, res) => {
  res.json({
    name: "crm247",
    description: "Multi-agent autonomous engagement platform",
    phase: "4-email-tracking",
    endpoints: {
      health: "/health",
      roadmap: [
        "GET /tracker/:domainId.js",
        "POST /track/visitor",
        "POST /track/events/batch",
        "POST /track/identify",
        "GET /track/visitors",
        "GET /track/events",
        "GET /contacts",
        "GET /contacts/:contactId/activity",
        "POST /emails/send",
        "GET /emails/messages",
        "GET /emails/events",
        "GET /email/open/:trackingId",
        "GET /email/click/:trackingId",
        "/engagement/runs"
      ]
    }
  });
});
