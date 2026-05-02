export type VisitorEventType =
  | "page_view"
  | "click"
  | "form_submit"
  | "time_on_page"
  | "exit_intent"
  | "custom";

export type EmailEventType =
  | "sent"
  | "opened"
  | "clicked"
  | "replied"
  | "bounced"
  | "unsubscribed";

export type AutonomyMode = "assisted" | "guardrailed" | "full";

export type IntentLevel = "Cold" | "Warm" | "Hot" | "Ready to Buy";

export type QueueStatus =
  | "pending_approval"
  | "queued"
  | "sent"
  | "paused"
  | "skipped"
  | "failed"
  | "blocked";

export interface Visitor {
  _id?: string;
  domainId: string;
  visitorId: string;
  contactId?: string;
  email?: string;
  firstSeenAt: string;
  lastSeenAt: string;
  pageViewCount: number;
  sessionCount: number;
  totalActiveMs: number;
  isIdentified: boolean;
}

export interface VisitorEvent {
  _id?: string;
  domainId: string;
  visitorId: string;
  contactId?: string;
  sessionId?: string;
  eventType: VisitorEventType;
  pageUrl: string;
  pageTitle?: string;
  metadata: Record<string, unknown>;
  timestamp: string;
}

export interface Contact {
  _id?: string;
  domainId: string;
  email: string;
  firstName?: string;
  lastName?: string;
  company?: string;
  isUnsubscribed: boolean;
  properties: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

export interface EngagementQueueItem {
  _id?: string;
  runId: string;
  contactId: string;
  status: QueueStatus;
  action: string;
  confidence: number;
  risk: "low" | "medium" | "high";
  reason: string;
  subject?: string;
  body?: string;
  policyDecision?: {
    allowed: boolean;
    reason?: string;
  };
  createdAt: string;
  updatedAt: string;
}

