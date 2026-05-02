import { Router } from "express";
import { pingMongo } from "../db/mongo.js";

export const healthRouter = Router();

healthRouter.get("/", async (_req, res) => {
  try {
    await pingMongo();
    res.json({
      ok: true,
      service: "crm247-api",
      mongo: "connected"
    });
  } catch (error) {
    res.status(503).json({
      ok: false,
      service: "crm247-api",
      mongo: "unavailable",
      error: error instanceof Error ? error.message : "Unknown error"
    });
  }
});

