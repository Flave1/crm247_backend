import { MongoClient, type Db } from "mongodb";
import { config } from "../config.js";

let client: MongoClient | null = null;
let database: Db | null = null;

export async function getMongoDb(): Promise<Db> {
  if (database) return database;

  client = new MongoClient(config.MONGODB_URI);
  await client.connect();
  database = client.db(config.MONGODB_DB);
  return database;
}

export async function pingMongo(): Promise<boolean> {
  const db = await getMongoDb();
  await db.command({ ping: 1 });
  return true;
}

export async function closeMongo(): Promise<void> {
  if (!client) return;
  await client.close();
  client = null;
  database = null;
}

