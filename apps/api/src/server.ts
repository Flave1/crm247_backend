import cors from "cors";
import express from "express";
import { config } from "./config.js";
import { getMongoDb } from "./db/mongo.js";
import { ensureIndexes } from "./db/indexes.js";
import { healthRouter } from "./routes/health.js";
import { rootRouter } from "./routes/root.js";
import { contactsRouter } from "./routes/contacts.js";
import { trackingRouter } from "./routes/tracking.js";

const app = express();

app.use((req, res, next) => {
  if (req.path.startsWith("/track") || req.path.startsWith("/tracker")) {
    res.header("Access-Control-Allow-Origin", "*");
    res.header("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
    res.header("Access-Control-Allow-Headers", "Content-Type,Accept,Origin");
    if (req.method === "OPTIONS") {
      res.sendStatus(204);
      return;
    }
  }
  next();
});

app.use(cors({ origin: config.WEB_ORIGIN, credentials: false }));
app.use(express.json({ limit: "1mb" }));

app.use("/", rootRouter);
app.use("/health", healthRouter);
app.use("/", trackingRouter);
app.use("/", contactsRouter);

async function start() {
  const db = await getMongoDb();
  await ensureIndexes(db);

  app.listen(config.API_PORT, () => {
    console.log(`crm247 API listening on http://localhost:${config.API_PORT}`);
  });
}

start().catch((error) => {
  console.error("Failed to start crm247 API", error);
  process.exit(1);
});
