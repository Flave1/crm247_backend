import dotenv from "dotenv";
import { z } from "zod";

dotenv.config({ path: "../../.env" });
dotenv.config();

const envSchema = z.object({
  NODE_ENV: z.string().default("development"),
  API_PORT: z.coerce.number().default(8080),
  API_ORIGIN: z.string().default("http://localhost:8080"),
  WEB_ORIGIN: z.string().default("http://localhost:5173"),
  MONGODB_URI: z.string().min(1, "MONGODB_URI is required"),
  MONGODB_DB: z.string().default("crm247"),
  EMAIL_FROM: z.string().default("no-reply@crm247.local"),
  EMAIL_PROVIDER: z.string().default("console")
});

export const config = envSchema.parse(process.env);
