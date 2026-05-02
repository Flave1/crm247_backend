import { Router } from "express";

export const rootRouter = Router();

rootRouter.get("/", (_req, res) => {
  res.json({
    name: "crm247",
    description: "Multi-agent autonomous engagement platform",
    phase: "2-cookie-tracking",
    endpoints: {
      health: "/health",
      roadmap: [
        "GET /tracker/:domainId.js",
        "POST /track/visitor",
        "POST /track/events/batch",
        "POST /track/identify",
        "GET /track/visitors",
        "GET /track/events",
        "/email/open/:trackingId",
        "/email/click/:trackingId",
        "/engagement/runs"
      ]
    }
  });
});
