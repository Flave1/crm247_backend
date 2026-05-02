export interface EngagementGraphState {
  runId: string;
  contactId: string;
  domainId: string;
  autonomyMode: "assisted" | "guardrailed" | "full";
  websiteSignals: unknown[];
  emailSignals: unknown[];
  retrievedContext: unknown[];
  intentScore?: number;
  recommendedAction?: string;
  draftSubject?: string;
  draftBody?: string;
  policyDecision?: {
    allowed: boolean;
    reason?: string;
  };
}

export function getEngagementGraphStatus() {
  return {
    implemented: false,
    phase: "5-langgraph-multi-agent-workflow",
    plannedAgents: [
      "Supervisor Agent",
      "Signal Ingestion Agent",
      "Identity Agent",
      "Intent Analyst Agent",
      "Retrieval Agent",
      "Strategy Agent",
      "Message Agent",
      "Policy Agent",
      "Delivery Agent",
      "Learning Agent"
    ]
  };
}

