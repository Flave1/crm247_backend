import cors from "cors";
import express from "express";
import { config } from "./config.js";
import { getMongoDb } from "./db/mongo.js";
import { ensureIndexes } from "./db/indexes.js";
import { healthRouter } from "./routes/health.js";
import { rootRouter } from "./routes/root.js";

const app = express();

app.use(cors({ origin: config.WEB_ORIGIN, credentials: false }));
app.use(express.json({ limit: "1mb" }));

app.use("/", rootRouter);
app.use("/health", healthRouter);

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

