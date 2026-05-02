import { Router } from "express";

export const rootRouter = Router();

rootRouter.get("/", (_req, res) => {
  res.json({
    name: "crm247",
    description: "Multi-agent autonomous engagement platform",
    phase: "1-foundation",
    endpoints: {
      health: "/health",
      roadmap: [
        "/tracker/:domainId.js",
        "/track/visitor",
        "/track/events/batch",
        "/track/identify",
        "/email/open/:trackingId",
        "/email/click/:trackingId",
        "/engagement/runs"
      ]
    }
  });
});

