from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote

from bson import ObjectId
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, RedirectResponse
from pydantic import BaseModel, EmailStr, Field
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError
from pymongo import ReturnDocument


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR.parent.parent / ".env")
load_dotenv()


class Settings:
    node_env = os.getenv("NODE_ENV", "development")
    api_port = int(os.getenv("API_PORT", "8080"))
    api_origin = os.getenv("API_ORIGIN", f"http://localhost:{api_port}")
    web_origin = os.getenv("WEB_ORIGIN", "http://localhost:5173")
    mongodb_uri = os.getenv("MONGODB_URI", "")
    mongodb_db = os.getenv("MONGODB_DB", "crm247")
    email_from = os.getenv("EMAIL_FROM", "no-reply@crm247.local")
    email_provider = os.getenv("EMAIL_PROVIDER", "console")
    auto_engagement_escalation_slack_channel = os.getenv(
        "AUTO_ENGAGEMENT_ESCALATION_SLACK_CHANNEL", ""
    ).strip()
    auto_engagement_escalation_teams_channel = os.getenv(
        "AUTO_ENGAGEMENT_ESCALATION_TEAMS_CHANNEL", ""
    ).strip()
    auto_engagement_escalation_sms_number = os.getenv(
        "AUTO_ENGAGEMENT_ESCALATION_SMS_NUMBER", ""
    ).strip()


settings = Settings()

if not settings.mongodb_uri:
    raise RuntimeError("MONGODB_URI is required")


app = FastAPI(title="crm247", description="Multi-agent autonomous engagement platform")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

mongo_client: MongoClient | None = None
mongo_db: Database | None = None

VisitorEventType = Literal[
    "page_view",
    "click",
    "form_submit",
    "time_on_page",
    "exit_intent",
    "custom",
]
AutonomyMode = Literal["assisted", "guardrailed", "full"]
EngagementRunStatus = Literal["draft", "running", "paused", "completed", "failed"]
EngagementQueueStatus = Literal[
    "pending_approval",
    "queued",
    "sent",
    "paused",
    "skipped",
    "failed",
    "blocked",
]
EngagementIntentLevel = Literal["Cold", "Warm", "Hot", "Ready to Buy"]
EngagementRiskLevel = Literal["low", "medium", "high"]
EngagementEscalationMedium = Literal["in_app", "slack", "teams", "sms"]

DEFAULT_GOAL = "checkout_recovery"
DEFAULT_CONFIDENCE_THRESHOLD = 72
DEFAULT_ESCALATION_MEDIA: list[EngagementEscalationMedium] = ["in_app"]
TRANSPARENT_GIF = (
    b"GIF89a\x01\x00\x01\x00\xf0\x00\x00\xff\xff\xff\x00\x00\x00!"
    b"\xf9\x04\x00\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00"
    b"\x00\x02\x02D\x01\x00;"
)


class VisitorRequest(BaseModel):
    domainId: str = Field(min_length=1, max_length=120)
    visitorId: str | None = Field(default=None, max_length=160)
    sessionId: str | None = Field(default=None, max_length=160)
    email: EmailStr | None = None
    pageUrl: str | None = Field(default=None, max_length=2048)
    pageTitle: str | None = Field(default=None, max_length=500)
    referrer: str | None = Field(default=None, max_length=2048)
    userAgent: str | None = Field(default=None, max_length=1000)
    properties: dict[str, Any] = Field(default_factory=dict)


class IdentifyRequest(BaseModel):
    domainId: str = Field(min_length=1, max_length=120)
    visitorId: str = Field(min_length=1, max_length=160)
    email: EmailStr
    properties: dict[str, Any] = Field(default_factory=dict)


class EventRequest(BaseModel):
    domainId: str = Field(min_length=1, max_length=120)
    visitorId: str = Field(min_length=1, max_length=160)
    sessionId: str | None = Field(default=None, max_length=160)
    eventType: VisitorEventType
    pageUrl: str = Field(min_length=1, max_length=2048)
    pageTitle: str | None = Field(default=None, max_length=500)
    referrer: str | None = Field(default=None, max_length=2048)
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: str | None = None


class BatchRequest(BaseModel):
    events: list[EventRequest] = Field(min_length=1, max_length=500)


class ContactPatchRequest(BaseModel):
    firstName: str | None = Field(default=None, max_length=120)
    lastName: str | None = Field(default=None, max_length=120)
    company: str | None = Field(default=None, max_length=180)
    properties: dict[str, Any] | None = None


class SendEmailRequest(BaseModel):
    domainId: str = Field(min_length=1, max_length=120)
    contactId: str | None = None
    to: EmailStr
    from_: EmailStr | None = Field(default=None, alias="from")
    subject: str = Field(min_length=1, max_length=240)
    html: str = Field(min_length=1, max_length=100000)
    text: str | None = Field(default=None, max_length=20000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class CreateEngagementRunRequest(BaseModel):
    domainId: str = Field(min_length=1, max_length=120)
    contactId: str = Field(min_length=1, max_length=120)
    name: str | None = Field(default=None, max_length=200)
    goal: str | None = Field(default=None, max_length=120)
    autonomyMode: AutonomyMode | None = None
    confidenceThreshold: int | None = Field(default=None, ge=0, le=100)
    contextDomain: str | None = Field(default=None, max_length=255)
    businessDescription: str | None = Field(default=None, max_length=4000)
    escalationMedia: list[EngagementEscalationMedium] | None = Field(default=None, max_length=4)
    escalationRecipientUserIds: list[str] | None = Field(default=None, max_length=20)
    escalationSlackChannelId: str | None = Field(default=None, max_length=120)
    escalationSlackChannelName: str | None = Field(default=None, max_length=120)
    escalationTeamsChannel: str | None = Field(default=None, max_length=255)
    escalationSmsNumber: str | None = Field(default=None, max_length=40)


class UpdateEngagementRunRequest(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    goal: str | None = Field(default=None, max_length=120)
    status: EngagementRunStatus | None = None
    autonomyMode: AutonomyMode | None = None
    confidenceThreshold: int | None = Field(default=None, ge=0, le=100)
    escalationMedia: list[EngagementEscalationMedium] | None = Field(default=None, max_length=4)
    escalationRecipientUserIds: list[str] | None = Field(default=None, max_length=20)
    escalationSlackChannelId: str | None = Field(default=None, max_length=120)
    escalationSlackChannelName: str | None = Field(default=None, max_length=120)
    escalationTeamsChannel: str | None = Field(default=None, max_length=255)
    escalationSmsNumber: str | None = Field(default=None, max_length=40)


class GenerateMessageRequest(BaseModel):
    regenerate: bool = False


class SaveMessageRequest(BaseModel):
    channel: str | None = Field(default=None, max_length=40)
    subject: str | None = Field(default=None, max_length=240)
    body: str = Field(min_length=1, max_length=20000)
    edited: bool = True


def get_db() -> Database:
    global mongo_client, mongo_db
    if mongo_db is not None:
        return mongo_db
    mongo_client = MongoClient(settings.mongodb_uri)
    mongo_db = mongo_client[settings.mongodb_db]
    return mongo_db


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def object_id_from(value: str | None) -> ObjectId | None:
    if not value or not ObjectId.is_valid(value):
        return None
    return ObjectId(value)


def normalize_email(value: str | None) -> str | None:
    email = (value or "").strip().lower()
    return email or None


def safe_timestamp(value: str | None) -> str:
    if not value:
        return now_iso()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        return now_iso()


def clamp(value: int | float, minimum: int, maximum: int) -> int:
    return max(minimum, min(int(value), maximum))


def active_ms_delta(metadata: dict[str, Any]) -> int:
    raw = metadata.get("activeMsDelta", metadata.get("active_ms_delta", 0))
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return 0
    if parsed <= 0:
        return 0
    return min(parsed, 60 * 60 * 1000)


def string_value(value: Any, fallback: str = "") -> str:
    return value if isinstance(value, str) else fallback


def iso_value(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def string_array(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            result.append(item.strip())
    return result


def normalize_escalation_media(value: Any) -> list[EngagementEscalationMedium]:
    items = [
        item
        for item in string_array(value)
        if item in {"in_app", "slack", "teams", "sms"}
    ]
    return items or list(DEFAULT_ESCALATION_MEDIA)


def ensure_indexes() -> None:
    db = get_db()
    db["visitors"].create_index([("domainId", 1), ("visitorId", 1)], unique=True)
    db["visitor_events"].create_index([("visitorId", 1), ("timestamp", -1)])
    db["visitor_events"].create_index([("domainId", 1), ("timestamp", -1)])
    db["contacts"].create_index([("domainId", 1), ("email", 1)], unique=True)
    db["contacts"].create_index([("domainId", 1), ("updatedAt", -1)])
    db["outbound_messages"].create_index([("trackingId", 1)], unique=True)
    db["outbound_messages"].create_index([("domainId", 1), ("createdAt", -1)])
    db["outbound_messages"].create_index([("contactId", 1), ("createdAt", -1)])
    db["email_events"].create_index([("contactId", 1), ("timestamp", -1)])
    db["email_events"].create_index([("trackingId", 1), ("timestamp", -1)])
    db["email_events"].create_index([("domainId", 1), ("timestamp", -1)])
    db["engagement_runs"].create_index([("id", 1)], unique=True)
    db["engagement_runs"].create_index([("status", 1), ("createdAt", -1)])
    db["engagement_runs"].create_index([("domainId", 1), ("createdAt", -1)])
    db["engagement_queue"].create_index([("id", 1)], unique=True)
    db["engagement_queue"].create_index([("runId", 1), ("createdAt", -1)])
    db["agent_decision_traces"].create_index([("id", 1)], unique=True)
    db["agent_decision_traces"].create_index([("runId", 1), ("contactId", 1), ("createdAt", -1)])
    db["agent_tasks"].create_index([("runId", 1), ("createdAt", -1)])
    db["agent_tasks"].create_index([("contactId", 1), ("createdAt", -1)])
    db["engagement_contact_states"].create_index([("runId", 1), ("contactId", 1)], unique=True)
    db["engagement_notifications"].create_index([("id", 1)], unique=True)
    db["engagement_notifications"].create_index([("runId", 1), ("createdAt", -1)])
    db["engagement_notifications"].create_index([("queueItemId", 1), ("createdAt", -1)])


@app.on_event("startup")
def startup_event() -> None:
    get_db().command({"ping": 1})
    ensure_indexes()


def public_contact(contact: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(contact.get("_id")) if contact.get("_id") else None,
        "domainId": contact.get("domainId"),
        "email": contact.get("email"),
        "firstName": contact.get("firstName"),
        "lastName": contact.get("lastName"),
        "company": contact.get("company"),
        "isUnsubscribed": bool(contact.get("isUnsubscribed")),
        "properties": contact.get("properties") or {},
        "createdAt": contact.get("createdAt"),
        "updatedAt": contact.get("updatedAt"),
        "lastWebsiteVisitAt": contact.get("lastWebsiteVisitAt"),
        "pageViewCount": int(contact.get("pageViewCount") or 0),
        "sessionCount": int(contact.get("sessionCount") or 0),
    }


def public_run(run: dict[str, Any] | None) -> dict[str, Any] | None:
    if not run:
        return None
    return {
        "id": run.get("id"),
        "name": run.get("name"),
        "goal": run.get("goal"),
        "domainId": run.get("domainId"),
        "contactId": run.get("contactId"),
        "autonomyMode": run.get("autonomyMode"),
        "status": run.get("status"),
        "enrolledCount": int(run.get("enrolledCount") or 0),
        "confidenceThreshold": int(run.get("confidenceThreshold") or 0),
        "contextDomain": run.get("contextDomain"),
        "businessDescription": run.get("businessDescription"),
        "escalationMedia": run.get("escalationMedia") or list(DEFAULT_ESCALATION_MEDIA),
        "escalationRecipientUserIds": run.get("escalationRecipientUserIds") or [],
        "escalationSlackChannelId": run.get("escalationSlackChannelId"),
        "escalationSlackChannelName": run.get("escalationSlackChannelName"),
        "escalationTeamsChannel": run.get("escalationTeamsChannel"),
        "escalationSmsNumber": run.get("escalationSmsNumber"),
        "signalSources": run.get("signalSources") or {},
        "analysisStatus": run.get("analysisStatus") or "pending",
        "analysisBatchSize": int(run.get("analysisBatchSize") or 0),
        "analysisTotalContacts": int(run.get("analysisTotalContacts") or 0),
        "analysisProcessedContacts": int(run.get("analysisProcessedContacts") or 0),
        "analysisStartedAt": run.get("analysisStartedAt"),
        "analysisCompletedAt": run.get("analysisCompletedAt"),
        "analysisError": run.get("analysisError"),
        "queueItemCount": int(run.get("queueItemCount") or 0),
        "latestQueueItemId": run.get("latestQueueItemId"),
        "latestIntentScore": run.get("latestIntentScore"),
        "latestIntentLevel": run.get("latestIntentLevel"),
        "latestRecommendedAction": run.get("latestRecommendedAction"),
        "createdAt": run.get("createdAt"),
        "updatedAt": run.get("updatedAt"),
    }


def public_queue_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "runId": item.get("runId"),
        "contactId": item.get("contactId"),
        "domainId": item.get("domainId"),
        "action": item.get("action"),
        "status": item.get("status"),
        "confidence": int(item.get("confidence") or 0),
        "risk": item.get("risk"),
        "reason": item.get("reason"),
        "policyReason": item.get("policyReason"),
        "shouldSendMessage": bool(item.get("shouldSendMessage")),
        "personalizedChannel": item.get("personalizedChannel"),
        "personalizedSubject": item.get("personalizedSubject"),
        "personalizedBody": item.get("personalizedBody"),
        "personalizedModelName": item.get("personalizedModelName"),
        "personalizedGeneratedAt": item.get("personalizedGeneratedAt"),
        "personalizedSavedAt": item.get("personalizedSavedAt"),
        "personalizedEdited": bool(item.get("personalizedEdited")),
        "deliveryStatus": item.get("deliveryStatus"),
        "deliveryMessageId": item.get("deliveryMessageId"),
        "deliveryError": item.get("deliveryError"),
        "retryCount": int(item.get("retryCount") or 0),
        "maxRetries": int(item.get("maxRetries") or 0),
        "scheduledSendAt": item.get("scheduledSendAt"),
        "nextAttemptAt": item.get("nextAttemptAt"),
        "processingStartedAt": item.get("processingStartedAt"),
        "lastErrorAt": item.get("lastErrorAt"),
        "deadLetteredAt": item.get("deadLetteredAt"),
        "escalationReason": item.get("escalationReason"),
        "createdByAgents": item.get("createdByAgents") or [],
        "createdAt": item.get("createdAt"),
        "updatedAt": item.get("updatedAt"),
        "executedAt": item.get("executedAt"),
    }


def public_trace(trace: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": trace.get("id"),
        "runId": trace.get("runId"),
        "queueItemId": trace.get("queueItemId"),
        "contactId": trace.get("contactId"),
        "agent": trace.get("agent"),
        "modelName": trace.get("modelName"),
        "aiEnabled": bool(trace.get("aiEnabled")),
        "usedAi": bool(trace.get("usedAi")),
        "fallbackReason": trace.get("fallbackReason"),
        "inputPayload": trace.get("inputPayload") or {},
        "deterministicPlan": trace.get("deterministicPlan") or {},
        "rawOutput": trace.get("rawOutput"),
        "parsedOutput": trace.get("parsedOutput"),
        "guardrailDecision": trace.get("guardrailDecision") or {},
        "createdAt": trace.get("createdAt"),
    }


def public_notification(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "runId": item.get("runId"),
        "queueItemId": item.get("queueItemId"),
        "contactId": item.get("contactId"),
        "medium": item.get("medium"),
        "recipientId": item.get("recipientId"),
        "status": item.get("status"),
        "reason": item.get("reason"),
        "title": item.get("title"),
        "body": item.get("body"),
        "metadata": item.get("metadata") or {},
        "createdAt": item.get("createdAt"),
        "updatedAt": item.get("updatedAt"),
    }


def normalize_run_name(contact: dict[str, Any], goal: str) -> str:
    label = " ".join(
        part for part in [string_value(contact.get("firstName")), string_value(contact.get("lastName"))] if part
    ).strip() or string_value(contact.get("email"), "contact")
    return f"{label} • {goal.replace('_', ' ')}"


def top_pages_from_signals(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    titles: dict[str, str | None] = {}
    for signal in signals:
        if signal.get("eventType") != "page_view":
            continue
        page_url = string_value(signal.get("pageUrl"))
        if not page_url:
            continue
        counts[page_url] = counts.get(page_url, 0) + 1
        titles[page_url] = signal.get("pageTitle")
    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)[:5]
    return [
        {"pageUrl": page_url, "pageTitle": titles.get(page_url), "count": count}
        for page_url, count in ranked
    ]


def compute_intent(
    website_signals: list[dict[str, Any]],
    email_signals: list[dict[str, Any]],
) -> tuple[int, EngagementIntentLevel, list[str]]:
    score = 0
    evidence: list[str] = []
    for event in website_signals:
        event_type = string_value(event.get("eventType"))
        page_url = string_value(event.get("pageUrl")).lower()
        if event_type == "page_view":
            score += 5
            if "product" in page_url:
                score += 10
                evidence.append("Viewed product content")
            if any(token in page_url for token in ("pricing", "checkout", "cart")):
                score += 20
                evidence.append("Viewed pricing or checkout pages")
        if event_type == "click":
            score += 20
            evidence.append("Clicked a tracked CTA")
        if event_type == "form_submit":
            score += 35
            evidence.append("Submitted a form")
        if event_type == "exit_intent":
            score += 10
            evidence.append("Triggered exit intent")
        if event_type == "time_on_page" and active_ms_delta(event.get("metadata") or {}) >= 60000:
            score += 8
            evidence.append("Spent meaningful time on site")
    for event in email_signals:
        event_type = string_value(event.get("eventType"))
        if event_type in {"opened", "open"}:
            score += 8
            evidence.append("Opened a tracked email")
        if event_type in {"clicked", "click"}:
            score += 20
            evidence.append("Clicked a tracked email")
        if event_type == "replied":
            score += 25
            evidence.append("Replied to an email")
    bounded = clamp(score, 0, 100)
    level: EngagementIntentLevel = "Cold"
    if bounded > 80:
        level = "Ready to Buy"
    elif bounded > 60:
        level = "Hot"
    elif bounded > 30:
        level = "Warm"
    return bounded, level, list(dict.fromkeys(evidence))[:6]


def summarize_retrieved_context(
    contact: dict[str, Any],
    website_signals: list[dict[str, Any]],
    email_signals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "type": "contact_summary",
            "email": contact.get("email"),
            "company": contact.get("company"),
            "lastWebsiteVisitAt": contact.get("lastWebsiteVisitAt") or contact.get("updatedAt"),
        },
        {
            "type": "website_summary",
            "topPages": top_pages_from_signals(website_signals)[:3],
            "websiteEventCount": len(website_signals),
        },
        {
            "type": "email_summary",
            "emailEventCount": len(email_signals),
            "lastEmailSentAt": contact.get("lastEmailSentAt"),
            "lastEmailOpenedAt": contact.get("lastEmailOpenedAt"),
            "lastEmailClickedAt": contact.get("lastEmailClickedAt"),
        },
    ]


def build_recommended_action(
    goal: str,
    intent_level: EngagementIntentLevel,
    contact: dict[str, Any],
    website_signals: list[dict[str, Any]],
    email_signals: list[dict[str, Any]],
) -> dict[str, str]:
    top_pages = top_pages_from_signals(website_signals)
    company = string_value(contact.get("company"))
    first_name = string_value(contact.get("firstName"), "there")
    brand = company or "your team"
    action = "wait"
    draft_subject = f"Quick follow-up for {first_name}"
    draft_body = (
        f"Hi {first_name},\n\n"
        f"I noticed interest around {goal.replace('_', ' ')} and wanted to follow up with a concise note.\n\n"
        "If it helps, I can share the quickest next step and answer any blockers.\n\n"
        f"Best,\n{brand}"
    )
    if intent_level == "Warm":
        action = "send_nurture_email"
        draft_subject = f"Helpful next step for {first_name}"
    if intent_level in {"Hot", "Ready to Buy"}:
        action = "send_demo_email" if goal == "demo_booking" else "send_recovery_email"
        top_page = top_pages[0]["pageUrl"] if top_pages else None
        draft_subject = "Still exploring a demo?" if goal == "demo_booking" else "Questions before you complete checkout?"
        prompt_line = (
            "If a short walkthrough would help, I can line up the fastest path to a demo."
            if goal == "demo_booking"
            else "If anything is blocking checkout, reply with the question and I will help unblock it quickly."
        )
        draft_body = (
            f"Hi {first_name},\n\n"
            f"You have been active on the site{', especially around ' + top_page if top_page else ''}, so this felt like the right time to help.\n\n"
            f"{prompt_line}\n\n"
            f"Best,\n{brand}"
        )
    rationale_parts = [f"{len(website_signals)} website events", f"{len(email_signals)} email events"]
    if top_pages:
        rationale_parts.append(f"top page {top_pages[0]['pageUrl']}")
    return {
        "action": action,
        "draftSubject": draft_subject,
        "draftBody": draft_body,
        "rationale": f"Recommended {action} based on {', '.join(rationale_parts)}.",
    }


def to_html_from_body(body: str) -> str:
    paragraphs = []
    for part in body.split("\n\n"):
        escaped = (
            part.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("\n", "<br />")
        )
        paragraphs.append(f"<p>{escaped}</p>")
    return "".join(paragraphs)


def build_policy_decision(
    autonomy_mode: AutonomyMode,
    confidence_threshold: int,
    confidence: int,
    contact: dict[str, Any],
    email_signals: list[dict[str, Any]],
) -> dict[str, Any]:
    last_email_sent_at = iso_value(contact.get("lastEmailSentAt"))
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    has_bounce = any(string_value(event.get("eventType")) in {"bounced", "bounce"} for event in email_signals)
    if bool(contact.get("isUnsubscribed")):
        return {
            "allowed": False,
            "reason": "Contact is unsubscribed",
            "policyReason": "unsubscribed",
            "risk": "high",
            "queueStatus": "blocked",
        }
    if has_bounce:
        return {
            "allowed": False,
            "reason": "A bounce exists for this contact",
            "policyReason": "bounced",
            "risk": "high",
            "queueStatus": "blocked",
        }
    if last_email_sent_at:
        sent_dt = datetime.fromisoformat(last_email_sent_at.replace("Z", "+00:00"))
        if sent_dt >= today:
            return {
                "allowed": False,
                "reason": "The last email was already sent today",
                "policyReason": "sent_today",
                "risk": "medium",
                "queueStatus": "blocked",
            }
    if confidence < confidence_threshold:
        return {
            "allowed": False,
            "reason": "Confidence is below the run threshold",
            "policyReason": "low_confidence",
            "risk": "medium",
            "queueStatus": "blocked",
        }
    if autonomy_mode == "full":
        return {
            "allowed": True,
            "reason": "Policy checks passed for full autonomy mode",
            "policyReason": None,
            "risk": "low" if confidence >= 85 else "medium",
            "queueStatus": "queued",
        }
    return {
        "allowed": True,
        "reason": (
            "Policy checks passed but approval is required in guardrailed mode"
            if autonomy_mode == "guardrailed"
            else "Policy checks passed but approval is required in assisted mode"
        ),
        "policyReason": "requires_approval",
        "risk": "low" if confidence >= 85 else "medium",
        "queueStatus": "pending_approval",
    }


def write_agent_task(db: Database, run_id: str, contact_id: str, agent: str, status: str, summary: str) -> None:
    timestamp = now_iso()
    db["agent_tasks"].insert_one(
        {
            "id": os.urandom(8).hex(),
            "runId": run_id,
            "contactId": contact_id,
            "agent": agent,
            "status": status,
            "summary": summary,
            "createdAt": timestamp,
            "updatedAt": timestamp,
        }
    )


def write_decision_trace(
    db: Database,
    run_id: str,
    contact_id: str,
    agent: str,
    input_payload: dict[str, Any],
    deterministic_plan: dict[str, Any],
    parsed_output: dict[str, Any] | None = None,
    guardrail_decision: dict[str, Any] | None = None,
    queue_item_id: str | None = None,
) -> None:
    db["agent_decision_traces"].insert_one(
        {
            "id": os.urandom(8).hex(),
            "runId": run_id,
            "queueItemId": queue_item_id,
            "contactId": contact_id,
            "agent": agent,
            "modelName": None,
            "aiEnabled": False,
            "usedAi": False,
            "fallbackReason": "python_deterministic_bootstrap",
            "inputPayload": input_payload,
            "deterministicPlan": deterministic_plan,
            "rawOutput": None,
            "parsedOutput": parsed_output,
            "guardrailDecision": guardrail_decision or {},
            "createdAt": now_iso(),
        }
    )


def update_run(db: Database, run_id: str, update: dict[str, Any]) -> None:
    db["engagement_runs"].update_one(
        {"id": run_id},
        {"$set": {**update, "updatedAt": now_iso()}},
    )


def load_run_context(db: Database, run_id: str, contact_id: str, domain_id: str) -> dict[str, Any]:
    contact_object_id = object_id_from(contact_id)
    if not contact_object_id:
        raise ValueError("Invalid contact id")
    contact = db["contacts"].find_one({"_id": contact_object_id, "domainId": domain_id})
    if not contact:
        raise ValueError("Contact not found")
    visitors = list(
        db["visitors"].find({"domainId": domain_id, "contactId": contact_id}).sort("lastSeenAt", -1).limit(20)
    )
    visitor_ids = [string_value(item.get("visitorId")) for item in visitors if item.get("visitorId")]
    website_query: dict[str, Any]
    if visitor_ids:
        website_query = {"domainId": domain_id, "$or": [{"contactId": contact_id}, {"visitorId": {"$in": visitor_ids}}]}
    else:
        website_query = {"domainId": domain_id, "contactId": contact_id}
    website_signals = list(
        db["visitor_events"].find(website_query).sort("timestamp", -1).limit(200)
    )
    email_signals = list(
        db["email_events"].find({"domainId": domain_id, "contactId": contact_id}).sort("timestamp", -1).limit(100)
    )
    recent_outbound = list(
        db["outbound_messages"]
        .find({"domainId": domain_id, "contactId": contact_id}, {"html": 0, "trackedHtml": 0})
        .sort("createdAt", -1)
        .limit(20)
    )
    write_agent_task(
        db,
        run_id,
        contact_id,
        "Signal Ingestion Agent",
        "completed",
        f"Loaded {len(website_signals)} website signals and {len(email_signals)} email signals",
    )
    return {
        "contact": contact,
        "visitors": visitors,
        "websiteSignals": website_signals,
        "emailSignals": email_signals,
        "recentOutboundMessages": recent_outbound,
    }


def create_escalation_notifications(
    db: Database,
    run: dict[str, Any],
    queue_item_id: str,
    contact_id: str,
    action: str,
    reason: str,
    confidence: int,
    risk: EngagementRiskLevel,
) -> None:
    media = normalize_escalation_media(run.get("escalationMedia"))
    if "in_app" not in media:
        return
    recipients = string_array(run.get("escalationRecipientUserIds")) or [None]
    timestamp = now_iso()
    notifications = [
        {
            "id": os.urandom(8).hex(),
            "runId": run.get("id"),
            "queueItemId": queue_item_id,
            "contactId": contact_id,
            "medium": "in_app",
            "recipientId": recipient,
            "status": "pending",
            "reason": reason,
            "title": f"Auto engagement escalation: {run.get('name')}",
            "body": f"Action {action} requires review. Reason: {reason}.",
            "metadata": {"confidence": confidence, "risk": risk},
            "createdAt": timestamp,
            "updatedAt": timestamp,
        }
        for recipient in recipients
    ]
    db["engagement_notifications"].insert_many(notifications)


def run_engagement_flow(db: Database, run_id: str) -> dict[str, Any]:
    run = db["engagement_runs"].find_one({"id": run_id})
    if not run:
        raise ValueError("Run not found")
    contact_id = string_value(run.get("contactId"))
    domain_id = string_value(run.get("domainId"))
    goal = string_value(run.get("goal"), DEFAULT_GOAL)
    autonomy_mode: AutonomyMode = run.get("autonomyMode") or "guardrailed"
    confidence_threshold = clamp(run.get("confidenceThreshold") or DEFAULT_CONFIDENCE_THRESHOLD, 0, 100)
    write_agent_task(db, run_id, contact_id, "Supervisor Agent", "started", "Starting engagement analysis")
    update_run(db, run_id, {"status": "running", "analysisStatus": "running", "analysisStartedAt": now_iso()})
    try:
        context = load_run_context(db, run_id, contact_id, domain_id)
        retrieved_context = summarize_retrieved_context(
            context["contact"], context["websiteSignals"], context["emailSignals"]
        )
        write_decision_trace(
            db,
            run_id,
            contact_id,
            "Signal Ingestion Agent",
            {"domainId": domain_id},
            {"step": "load_context"},
            {
                "visitors": len(context["visitors"]),
                "websiteSignals": len(context["websiteSignals"]),
                "emailSignals": len(context["emailSignals"]),
            },
        )
        write_agent_task(
            db,
            run_id,
            contact_id,
            "Identity Agent",
            "completed",
            "Contact linked to tracked visitors" if context["visitors"] else "No linked visitors",
        )
        intent_score, intent_level, evidence = compute_intent(context["websiteSignals"], context["emailSignals"])
        confidence = clamp(intent_score + (10 if intent_level == "Ready to Buy" else 5 if intent_level == "Hot" else 0), 35, 99)
        write_agent_task(
            db,
            run_id,
            contact_id,
            "Intent Analyst Agent",
            "completed",
            f"{intent_level} intent at score {intent_score}",
        )
        write_decision_trace(
            db,
            run_id,
            contact_id,
            "Intent Analyst Agent",
            {"websiteSignalCount": len(context["websiteSignals"]), "emailSignalCount": len(context["emailSignals"])},
            {"scoringModel": "phase_6_bootstrap"},
            {"intentScore": intent_score, "intentLevel": intent_level, "evidence": evidence, "confidence": confidence},
        )
        recommendation = build_recommended_action(
            goal, intent_level, context["contact"], context["websiteSignals"], context["emailSignals"]
        )
        write_agent_task(db, run_id, contact_id, "Strategy Agent", "completed", f"Recommended {recommendation['action']}")
        write_agent_task(db, run_id, contact_id, "Message Agent", "completed", "Drafted a personalized outreach message")
        write_decision_trace(
            db,
            run_id,
            contact_id,
            "Strategy Agent",
            {"goal": goal, "intentLevel": intent_level},
            {"step": "plan_actions", "mode": "deterministic"},
            recommendation,
        )
        policy_decision = build_policy_decision(
            autonomy_mode, confidence_threshold, confidence, context["contact"], context["emailSignals"]
        )
        write_agent_task(
            db,
            run_id,
            contact_id,
            "Policy Agent",
            "completed" if policy_decision["allowed"] else "failed",
            policy_decision["reason"],
        )
        write_decision_trace(
            db,
            run_id,
            contact_id,
            "Policy Agent",
            {"autonomyMode": autonomy_mode, "confidenceThreshold": confidence_threshold, "confidence": confidence},
            {"step": "policy_guardrails"},
            policy_decision,
            policy_decision,
        )
        queue_item_id = os.urandom(8).hex()
        timestamp = now_iso()
        queue_item = {
            "id": queue_item_id,
            "runId": run_id,
            "contactId": contact_id,
            "domainId": domain_id,
            "action": recommendation["action"],
            "status": policy_decision["queueStatus"],
            "confidence": confidence,
            "risk": policy_decision["risk"],
            "reason": recommendation["rationale"],
            "policyReason": policy_decision["policyReason"],
            "shouldSendMessage": recommendation["action"].startswith("send_"),
            "personalizedChannel": "email",
            "personalizedSubject": recommendation["draftSubject"],
            "personalizedBody": recommendation["draftBody"],
            "personalizedModelName": None,
            "personalizedGeneratedAt": timestamp,
            "personalizedSavedAt": None,
            "personalizedEdited": False,
            "deliveryStatus": "queued" if policy_decision["queueStatus"] == "queued" else None,
            "deliveryMessageId": None,
            "deliveryError": None,
            "retryCount": 0,
            "maxRetries": 3,
            "scheduledSendAt": None,
            "nextAttemptAt": None,
            "processingStartedAt": None,
            "lastErrorAt": None,
            "deadLetteredAt": None,
            "escalationReason": None,
            "createdByAgents": [
                "Signal Ingestion Agent",
                "Identity Agent",
                "Intent Analyst Agent",
                "Strategy Agent",
                "Message Agent",
                "Policy Agent",
                "Delivery Agent",
            ],
            "createdAt": timestamp,
            "updatedAt": timestamp,
            "executedAt": None,
        }
        db["engagement_queue"].insert_one(queue_item)
        if policy_decision["queueStatus"] in {"pending_approval", "blocked"}:
            create_escalation_notifications(
                db,
                run,
                queue_item_id,
                contact_id,
                recommendation["action"],
                policy_decision["reason"],
                confidence,
                policy_decision["risk"],
            )
        db["engagement_contact_states"].update_one(
            {"runId": run_id, "contactId": contact_id},
            {
                "$setOnInsert": {"id": os.urandom(8).hex(), "createdAt": timestamp},
                "$set": {
                    "runId": run_id,
                    "contactId": contact_id,
                    "domainId": domain_id,
                    "lastAnalyzedAt": timestamp,
                    "nextCheckInAt": None,
                    "lastReasoningSummary": recommendation["rationale"],
                    "lastQueueItemId": queue_item_id,
                    "updatedAt": timestamp,
                },
                "$inc": {"analysisCount": 1},
            },
            upsert=True,
        )
        write_agent_task(
            db,
            run_id,
            contact_id,
            "Delivery Agent",
            "completed",
            f"Created queue item with status {policy_decision['queueStatus']}",
        )
        write_decision_trace(
            db,
            run_id,
            contact_id,
            "Delivery Agent",
            {"recommendedAction": recommendation["action"], "queueStatus": policy_decision["queueStatus"]},
            {"step": "queue_action"},
            {
                "queueItemId": queue_item_id,
                "queueStatus": policy_decision["queueStatus"],
                "deliveryStatus": "queued" if policy_decision["queueStatus"] == "queued" else None,
            },
            policy_decision,
            queue_item_id,
        )
        update_run(
            db,
            run_id,
            {
                "status": "completed",
                "analysisStatus": "completed",
                "analysisProcessedContacts": 1,
                "analysisCompletedAt": timestamp,
                "queueItemCount": 1,
                "latestQueueItemId": queue_item_id,
                "latestIntentScore": intent_score,
                "latestIntentLevel": intent_level,
                "latestRecommendedAction": recommendation["action"],
            },
        )
        write_agent_task(db, run_id, contact_id, "Supervisor Agent", "completed", "Completed engagement analysis")
        write_decision_trace(
            db,
            run_id,
            contact_id,
            "Supervisor Agent",
            {"goal": goal, "autonomyMode": autonomy_mode},
            {"step": "supervisor_summary"},
            {
                "intentScore": intent_score,
                "intentLevel": intent_level,
                "recommendedAction": recommendation["action"],
                "queueItemId": queue_item_id,
                "queueStatus": policy_decision["queueStatus"],
            },
            policy_decision,
            queue_item_id,
        )
        return {
            "intentScore": intent_score,
            "intentLevel": intent_level,
            "recommendedAction": recommendation["action"],
            "queueItemId": queue_item_id,
            "queueStatus": policy_decision["queueStatus"],
            "policyDecision": policy_decision,
            "retrievedContext": retrieved_context,
        }
    except Exception as error:
        update_run(
            db,
            run_id,
            {
                "status": "failed",
                "analysisStatus": "failed",
                "analysisError": str(error),
                "analysisCompletedAt": now_iso(),
            },
        )
        write_agent_task(db, run_id, contact_id, "Supervisor Agent", "failed", str(error))
        raise


def get_run_and_queue_item_or_404(db: Database, run_id: str, queue_item_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    run = db["engagement_runs"].find_one({"id": run_id})
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    item = db["engagement_queue"].find_one({"runId": run_id, "id": queue_item_id})
    if not item:
        raise HTTPException(status_code=404, detail="Queue item not found")
    return run, item


def generate_queue_message_draft(db: Database, run: dict[str, Any], item: dict[str, Any]) -> dict[str, str]:
    context = load_run_context(db, string_value(run.get("id")), string_value(item.get("contactId")), string_value(run.get("domainId")))
    recommendation = build_recommended_action(
        string_value(run.get("goal"), DEFAULT_GOAL),
        run.get("latestIntentLevel") or "Cold",
        context["contact"],
        context["websiteSignals"],
        context["emailSignals"],
    )
    return {
        "personalizedChannel": "email",
        "personalizedSubject": recommendation["draftSubject"],
        "personalizedBody": recommendation["draftBody"],
        "reason": recommendation["rationale"],
    }


def send_tracked_email(
    db: Database,
    *,
    domain_id: str,
    to: str,
    subject: str,
    html: str,
    request_meta: dict[str, Any],
    contact_id: str | None = None,
    from_email: str | None = None,
    text: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    timestamp = now_iso()
    metadata = metadata or {}
    normalized_email = normalize_email(to)
    if not normalized_email:
        raise ValueError("Unable to create or load contact")
    contact_object_id = object_id_from(contact_id)
    contact: dict[str, Any] | None = None
    if contact_object_id:
        contact = db["contacts"].find_one({"_id": contact_object_id, "domainId": domain_id})
    if not contact:
        contact = db["contacts"].find_one_and_update(
            {"domainId": domain_id, "email": normalized_email},
            {
                "$setOnInsert": {
                    "domainId": domain_id,
                    "email": normalized_email,
                    "isUnsubscribed": False,
                    "properties": {},
                    "createdAt": timestamp,
                },
                "$set": {"updatedAt": timestamp},
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    if not contact:
        raise ValueError("Unable to create or load contact")
    actual_contact_id = str(contact["_id"])
    tracking_id = f"em_{os.urandom(8).hex()}"
    tracked_html = inject_tracking_pixel(rewrite_links(html, tracking_id), tracking_id)
    message = {
        "domainId": domain_id,
        "contactId": actual_contact_id,
        "trackingId": tracking_id,
        "provider": settings.email_provider,
        "status": "sent",
        "from": normalize_email(from_email) or settings.email_from,
        "to": normalized_email,
        "subject": subject,
        "html": html,
        "trackedHtml": tracked_html,
        "text": text,
        "metadata": metadata,
        "openCount": 0,
        "clickCount": 0,
        "lastOpenedAt": None,
        "lastClickedAt": None,
        "createdAt": timestamp,
        "sentAt": timestamp,
        "updatedAt": timestamp,
    }
    result = db["outbound_messages"].insert_one(message)
    db["contacts"].update_one(
        {"_id": contact["_id"]},
        {
            "$set": {"updatedAt": timestamp, "lastEmailSentAt": timestamp, "lastEmailSubject": subject},
            "$inc": {"emailSentCount": 1},
        },
    )
    db["email_events"].insert_one(
        {
            "domainId": domain_id,
            "contactId": actual_contact_id,
            "messageId": str(result.inserted_id),
            "trackingId": tracking_id,
            "eventType": "sent",
            "subject": subject,
            "targetUrl": None,
            "userAgent": request_meta.get("userAgent"),
            "ip": request_meta.get("ip"),
            "metadata": metadata,
            "timestamp": timestamp,
            "createdAt": timestamp,
        }
    )
    return {
        "id": str(result.inserted_id),
        "contactId": actual_contact_id,
        "trackingId": tracking_id,
        "status": "sent",
        "provider": settings.email_provider,
        "to": normalized_email,
        "subject": subject,
        "openUrl": f"{settings.api_origin.rstrip('/')}/email/open/{tracking_id}.gif",
        "previewHtml": tracked_html,
    }


def rewrite_links(html: str, tracking_id: str) -> str:
    def replace(match: Any) -> str:
        quote = match.group(1)
        raw_url = match.group(2).strip()
        if not raw_url or raw_url.startswith(("#", "mailto:", "tel:", "javascript:")):
            return match.group(0)
        tracked_url = f"{settings.api_origin.rstrip('/')}/email/click/{tracking_id}?u={raw_url}"
        return f"href={quote}{tracked_url}{quote}"

    import re

    return re.sub(r'href=(["\'])(.*?)\1', replace, html, flags=re.IGNORECASE)


def inject_tracking_pixel(html: str, tracking_id: str) -> str:
    pixel_url = f"{settings.api_origin.rstrip('/')}/email/open/{tracking_id}.gif"
    pixel = f'<img src="{pixel_url}" width="1" height="1" alt="" style="display:none!important;opacity:0;width:1px;height:1px;" />'
    if "</body>" in html.lower():
        lower = html.lower()
        index = lower.rfind("</body>")
        return f"{html[:index]}{pixel}{html[index:]}"
    return html + pixel


def approve_queue_item(db: Database, run_id: str, queue_item_id: str) -> dict[str, Any]:
    run, item = get_run_and_queue_item_or_404(db, run_id, queue_item_id)
    status = string_value(item.get("status"))
    timestamp = now_iso()
    if status == "blocked":
        raise HTTPException(status_code=400, detail="Queue item is blocked by policy")
    if status in {"sent", "skipped"}:
        return item
    if not bool(item.get("shouldSendMessage")):
        db["engagement_queue"].update_one(
            {"runId": run_id, "id": queue_item_id},
            {"$set": {"status": "skipped", "executedAt": timestamp, "updatedAt": timestamp, "deliveryStatus": None, "deliveryMessageId": None}},
        )
        write_decision_trace(
            db,
            run_id,
            string_value(item.get("contactId")),
            "Delivery Agent",
            {"status": status, "shouldSendMessage": False},
            {"step": "approve_queue_item", "mode": "skip_no_send"},
            {"status": "skipped"},
            queue_item_id=queue_item_id,
        )
        updated = db["engagement_queue"].find_one({"runId": run_id, "id": queue_item_id})
        assert updated is not None
        return updated
    subject = string_value(item.get("personalizedSubject"))
    body = string_value(item.get("personalizedBody"))
    if not subject or not body:
        generated = generate_queue_message_draft(db, run, item)
        subject = generated["personalizedSubject"]
        body = generated["personalizedBody"]
        db["engagement_queue"].update_one(
            {"runId": run_id, "id": queue_item_id},
            {"$set": {"personalizedChannel": "email", "personalizedSubject": subject, "personalizedBody": body, "personalizedGeneratedAt": timestamp, "updatedAt": timestamp}},
        )
    contact = db["contacts"].find_one({"_id": object_id_from(string_value(item.get("contactId"))), "domainId": string_value(run.get("domainId"))})
    if not contact or not isinstance(contact.get("email"), str):
        raise HTTPException(status_code=400, detail="Contact email is missing")
    message = send_tracked_email(
        db,
        domain_id=string_value(run.get("domainId")),
        contact_id=string_value(item.get("contactId")),
        to=contact["email"],
        subject=subject,
        html=to_html_from_body(body),
        text=body,
        metadata={"source": "engagement_queue_approval", "runId": run_id, "queueItemId": queue_item_id, "action": item.get("action")},
        request_meta={"userAgent": "engagement-queue-approve", "ip": None},
    )
    db["engagement_queue"].update_one(
        {"runId": run_id, "id": queue_item_id},
        {
            "$set": {
                "status": "sent",
                "deliveryStatus": "sent",
                "deliveryMessageId": message["id"],
                "executedAt": timestamp,
                "updatedAt": timestamp,
                "personalizedChannel": "email",
                "personalizedSubject": subject,
                "personalizedBody": body,
            }
        },
    )
    write_agent_task(db, run_id, string_value(item.get("contactId")), "Delivery Agent", "completed", f"Approved and sent queue item {queue_item_id}")
    write_decision_trace(
        db,
        run_id,
        string_value(item.get("contactId")),
        "Delivery Agent",
        {"status": status, "action": item.get("action")},
        {"step": "approve_queue_item", "mode": "send_tracked_email"},
        {"deliveryMessageId": message["id"], "deliveryTrackingId": message["trackingId"], "status": "sent"},
        queue_item_id=queue_item_id,
    )
    updated = db["engagement_queue"].find_one({"runId": run_id, "id": queue_item_id})
    assert updated is not None
    return updated


def pause_queue_item(db: Database, run_id: str, queue_item_id: str) -> dict[str, Any]:
    _, item = get_run_and_queue_item_or_404(db, run_id, queue_item_id)
    timestamp = now_iso()
    db["engagement_queue"].update_one({"runId": run_id, "id": queue_item_id}, {"$set": {"status": "paused", "updatedAt": timestamp}})
    write_decision_trace(
        db,
        run_id,
        string_value(item.get("contactId")),
        "Delivery Agent",
        {"previousStatus": item.get("status")},
        {"step": "pause_queue_item"},
        {"status": "paused"},
        queue_item_id=queue_item_id,
    )
    updated = db["engagement_queue"].find_one({"runId": run_id, "id": queue_item_id})
    assert updated is not None
    return updated


def generate_queue_item_message(db: Database, run_id: str, queue_item_id: str, regenerate: bool) -> dict[str, Any]:
    run, item = get_run_and_queue_item_or_404(db, run_id, queue_item_id)
    if not regenerate and string_value(item.get("personalizedSubject")) and string_value(item.get("personalizedBody")):
        return item
    generated = generate_queue_message_draft(db, run, item)
    timestamp = now_iso()
    db["engagement_queue"].update_one(
        {"runId": run_id, "id": queue_item_id},
        {
            "$set": {
                "personalizedChannel": generated["personalizedChannel"],
                "personalizedSubject": generated["personalizedSubject"],
                "personalizedBody": generated["personalizedBody"],
                "personalizedGeneratedAt": timestamp,
                "updatedAt": timestamp,
            }
        },
    )
    write_agent_task(db, run_id, string_value(item.get("contactId")), "Message Agent", "completed", f"Generated message for queue item {queue_item_id}")
    write_decision_trace(
        db,
        run_id,
        string_value(item.get("contactId")),
        "Message Agent",
        {"regenerate": regenerate},
        {"step": "generate_queue_item_message"},
        generated,
        queue_item_id=queue_item_id,
    )
    updated = db["engagement_queue"].find_one({"runId": run_id, "id": queue_item_id})
    assert updated is not None
    return updated


def save_queue_item_message(db: Database, run_id: str, queue_item_id: str, payload: SaveMessageRequest) -> dict[str, Any]:
    _, item = get_run_and_queue_item_or_404(db, run_id, queue_item_id)
    timestamp = now_iso()
    update: dict[str, Any] = {
        "updatedAt": timestamp,
        "personalizedSavedAt": timestamp,
        "personalizedEdited": payload.edited,
    }
    if payload.channel and payload.channel.strip():
        update["personalizedChannel"] = payload.channel.strip()
    if payload.subject is not None:
        update["personalizedSubject"] = payload.subject.strip()
    update["personalizedBody"] = payload.body
    db["engagement_queue"].update_one({"runId": run_id, "id": queue_item_id}, {"$set": update})
    write_decision_trace(
        db,
        run_id,
        string_value(item.get("contactId")),
        "Message Agent",
        {"edited": payload.edited},
        {"step": "save_queue_item_message"},
        {
            "personalizedChannel": update.get("personalizedChannel") or item.get("personalizedChannel"),
            "personalizedSubject": update.get("personalizedSubject") or item.get("personalizedSubject"),
        },
        queue_item_id=queue_item_id,
    )
    updated = db["engagement_queue"].find_one({"runId": run_id, "id": queue_item_id})
    assert updated is not None
    return updated


def build_tracker_script(domain_id: str) -> str:
    safe_domain_id = json.dumps(domain_id)
    fallback_origin = json.dumps(settings.api_origin)
    return f"""(function(window, document) {{
  "use strict";

  if (!window || !document) return;

  var COOKIE_NAME = "eg_visitor_id";
  var SESSION_KEY = "crm247.session";
  var DOMAIN_ID = {safe_domain_id};
  var FALLBACK_ORIGIN = {fallback_origin};
  var BATCH_SIZE = 10;
  var BATCH_INTERVAL_MS = 5000;
  var SESSION_TIMEOUT_MS = 30 * 60 * 1000;
  var HEARTBEAT_MS = 15000;

  var state = {{
    visitorId: null,
    sessionId: null,
    queue: [],
    ready: false,
    pageStartedAt: Date.now(),
    lastActiveSentAt: Date.now(),
    pageVisitId: makeId("pv"),
    eventSeq: 0,
    batchTimer: null,
    heartbeatTimer: null
  }};

  function currentScriptOrigin() {{
    try {{
      var script = document.currentScript;
      if (!script || !script.src) {{
        var scripts = document.getElementsByTagName("script");
        for (var i = scripts.length - 1; i >= 0; i--) {{
          if (scripts[i] && scripts[i].src && scripts[i].src.indexOf("/tracker/") !== -1) {{
            script = scripts[i];
            break;
          }}
        }}
      }}
      if (script && script.src) return new URL(script.src).origin;
    }} catch (error) {{}}
    return FALLBACK_ORIGIN;
  }}

  function endpoint(path) {{
    return currentScriptOrigin() + path;
  }}

  function makeId(prefix) {{
    if (window.crypto && typeof window.crypto.randomUUID === "function") {{
      return prefix + "_" + window.crypto.randomUUID();
    }}
    return prefix + "_" + Math.random().toString(36).slice(2) + Date.now().toString(36);
  }}

  function setCookie(name, value, days) {{
    var date = new Date();
    date.setTime(date.getTime() + days * 24 * 60 * 60 * 1000);
    document.cookie = name + "=" + encodeURIComponent(value) + "; expires=" + date.toUTCString() + "; path=/; SameSite=Lax";
  }}

  function getCookie(name) {{
    var parts = document.cookie ? document.cookie.split(";") : [];
    for (var i = 0; i < parts.length; i++) {{
      var part = parts[i].trim();
      if (part.indexOf(name + "=") === 0) {{
        return decodeURIComponent(part.substring(name.length + 1));
      }}
    }}
    return null;
  }}

  function readSession() {{
    try {{
      var raw = window.localStorage.getItem(SESSION_KEY);
      return raw ? JSON.parse(raw) : null;
    }} catch (error) {{
      return null;
    }}
  }}

  function writeSession(session) {{
    try {{
      window.localStorage.setItem(SESSION_KEY, JSON.stringify(session));
    }} catch (error) {{}}
  }}

  function getSessionId() {{
    var now = Date.now();
    var existing = readSession();
    if (existing && existing.id && existing.lastSeenAt && now - existing.lastSeenAt < SESSION_TIMEOUT_MS) {{
      existing.lastSeenAt = now;
      writeSession(existing);
      return existing.id;
    }}
    var next = {{ id: makeId("sess"), createdAt: now, lastSeenAt: now }};
    writeSession(next);
    return next.id;
  }}

  function visitorId() {{
    var existing = getCookie(COOKIE_NAME);
    if (existing) return existing;
    var next = makeId("v");
    setCookie(COOKIE_NAME, next, 365);
    return next;
  }}

  function postJSON(path, body, keepalive) {{
    var payload = JSON.stringify(body);
    if (typeof fetch === "function") {{
      return fetch(endpoint(path), {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: payload,
        keepalive: !!keepalive,
        credentials: "omit"
      }}).then(function(resp) {{
        return resp.text().then(function(text) {{
          var json = null;
          try {{ json = text ? JSON.parse(text) : null; }} catch (error) {{}}
          return {{ ok: resp.ok, status: resp.status, json: json }};
        }});
      }}).catch(function() {{
        return {{ ok: false, status: 0, json: null }};
      }});
    }}
    return Promise.resolve({{ ok: false, status: 0, json: null }});
  }}

  function baseEvent(eventType, metadata) {{
    state.eventSeq += 1;
    return {{
      domainId: DOMAIN_ID,
      visitorId: state.visitorId,
      sessionId: state.sessionId,
      eventType: eventType,
      pageUrl: window.location.href,
      pageTitle: document.title || "",
      referrer: document.referrer || null,
      timestamp: new Date().toISOString(),
      metadata: Object.assign({{
        pageVisitId: state.pageVisitId,
        eventSeq: state.eventSeq,
        sdk: "crm247-js",
        source: "website",
        viewport: {{
          width: window.innerWidth || null,
          height: window.innerHeight || null
        }}
      }}, metadata || {{}})
    }};
  }}

  function enqueue(event) {{
    state.queue.push(event);
    if (state.queue.length >= BATCH_SIZE) flush(false);
  }}

  function flush(useBeacon) {{
    if (!state.ready || state.queue.length === 0) return;
    var batch = state.queue.splice(0, state.queue.length);
    var body = {{ events: batch }};
    if (useBeacon && navigator.sendBeacon) {{
      try {{
        var blob = new Blob([JSON.stringify(body)], {{ type: "application/json" }});
        if (navigator.sendBeacon(endpoint("/track/events/batch"), blob)) return;
      }} catch (error) {{}}
    }}
    postJSON("/track/events/batch", body, false).then(function(result) {{
      if (!result.ok) state.queue = batch.concat(state.queue);
    }});
  }}

  function register(email, properties) {{
    return postJSON("/track/visitor", {{
      domainId: DOMAIN_ID,
      visitorId: state.visitorId,
      sessionId: state.sessionId,
      email: email || null,
      pageUrl: window.location.href,
      pageTitle: document.title || "",
      referrer: document.referrer || null,
      userAgent: navigator.userAgent || null,
      properties: properties || {{}}
    }}, false).then(function(result) {{
      state.ready = !!result.ok;
      if (result.json && result.json.visitorId) {{
        state.visitorId = result.json.visitorId;
        setCookie(COOKIE_NAME, state.visitorId, 365);
      }}
      if (state.ready) flush(false);
      return result;
    }});
  }}

  function identify(email, properties) {{
    if (!email) return Promise.resolve({{ ok: false }});
    return postJSON("/track/identify", {{
      domainId: DOMAIN_ID,
      visitorId: state.visitorId,
      email: email,
      properties: properties || {{}}
    }}, false).then(function(result) {{
      register(email, properties || {{}});
      return result;
    }});
  }}

  function track(eventType, metadata) {{
    enqueue(baseEvent(eventType || "custom", metadata || {{}}));
  }}

  function setupClickTracking() {{
    document.addEventListener("click", function(event) {{
      var target = event.target;
      if (!target) return;
      var element = target.closest ? target.closest("a,button,[data-track-id]") : target;
      if (!element) return;
      track("click", {{
        elementTag: element.tagName || null,
        elementId: element.id || null,
        trackId: element.getAttribute ? element.getAttribute("data-track-id") : null,
        text: element.textContent ? String(element.textContent).trim().slice(0, 160) : null,
        href: element.href || null
      }});
    }}, true);
  }}

  function setupFormTracking() {{
    document.addEventListener("submit", function(event) {{
      var form = event.target;
      if (!form || form.tagName !== "FORM") return;
      var emailInput = form.querySelector('input[type="email"], input[name="email"]');
      var email = emailInput && emailInput.value ? String(emailInput.value).trim().toLowerCase() : null;
      track("form_submit", {{
        formId: form.id || null,
        email: email,
        emailPresent: !!email
      }});
      if (email) identify(email, {{ source: "form_submit" }});
    }}, true);
  }}

  function setupExitIntent() {{
    var lastExit = 0;
    document.addEventListener("mouseout", function(event) {{
      if (event.relatedTarget || event.toElement) return;
      if (typeof event.clientY === "number" && event.clientY > 12) return;
      var now = Date.now();
      if (now - lastExit < 15000) return;
      if (now - state.pageStartedAt < 3000) return;
      lastExit = now;
      track("exit_intent", {{ reason: "mouse_top_exit" }});
    }}, true);
  }}

  function startHeartbeat() {{
    state.heartbeatTimer = window.setInterval(function() {{
      var now = Date.now();
      var delta = now - state.lastActiveSentAt;
      if (delta < 1000) return;
      state.lastActiveSentAt = now;
      track("time_on_page", {{ activeMsDelta: delta }});
    }}, HEARTBEAT_MS);
  }}

  function init() {{
    state.visitorId = visitorId();
    state.sessionId = getSessionId();
    setupClickTracking();
    setupFormTracking();
    setupExitIntent();
    startHeartbeat();
    register(null, {{}});
    track("page_view", {{}});
    state.batchTimer = window.setInterval(function() {{ flush(false); }}, BATCH_INTERVAL_MS);
    window.addEventListener("pagehide", function() {{ flush(true); }});
    window.addEventListener("beforeunload", function() {{ flush(true); }});
  }}

  window.CRM247 = {{
    track: track,
    identify: identify,
    flush: function() {{ flush(false); }},
    getState: function() {{
      return {{
        domainId: DOMAIN_ID,
        visitorId: state.visitorId,
        sessionId: state.sessionId,
        queueLength: state.queue.length,
        ready: state.ready
      }};
    }}
  }};

  init();
}})(window, document);"""


def parse_query_int(value: str | None, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value or default)
    except ValueError:
        return default
    return max(minimum, min(parsed, maximum))


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "name": "crm247",
        "description": "Multi-agent autonomous engagement platform",
        "phase": "5-python-backend",
        "endpoints": {
            "health": "/health",
            "roadmap": [
                "GET /tracker/:domainId.js",
                "POST /track/visitor",
                "POST /track/events/batch",
                "POST /track/identify",
                "GET /track/visitors",
                "GET /track/events",
                "GET /contacts",
                "GET /contacts/:contactId",
                "PATCH /contacts/:contactId",
                "GET /contacts/:contactId/activity",
                "POST /emails/send",
                "GET /emails/messages",
                "GET /emails/events",
                "GET /email/open/:trackingId",
                "GET /email/click/:trackingId",
                "POST /engagement/runs",
                "GET /engagement/runs",
                "GET /engagement/runs/:runId",
                "PATCH /engagement/runs/:runId",
                "GET /engagement/runs/:runId/queue",
                "GET /engagement/runs/:runId/queue/:queueItemId",
                "POST /engagement/runs/:runId/queue/:queueItemId/approve",
                "POST /engagement/runs/:runId/queue/:queueItemId/pause",
                "POST /engagement/runs/:runId/queue/:queueItemId/generate-message",
                "PUT /engagement/runs/:runId/queue/:queueItemId/message",
                "GET /engagement/runs/:runId/decision-traces",
                "GET /engagement/runs/:runId/graph",
                "GET /engagement/runs/:runId/notifications",
            ],
        },
    }


@app.get("/health")
def health() -> dict[str, Any]:
    get_db().command({"ping": 1})
    return {"ok": True, "service": "crm247-api", "mongo": "ok"}


@app.get("/tracker/{domain_id}.js", response_class=PlainTextResponse)
def tracker_script(domain_id: str) -> PlainTextResponse:
    normalized = domain_id.strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="Missing domain id")
    return PlainTextResponse(build_tracker_script(normalized), media_type="application/javascript; charset=utf-8", headers={"Cache-Control": "no-store"})


@app.post("/track/visitor")
def track_visitor(payload: VisitorRequest) -> dict[str, Any]:
    db = get_db()
    timestamp = now_iso()
    visitor_id = payload.visitorId or f"v_{os.urandom(8).hex()}"
    email = normalize_email(str(payload.email) if payload.email else None)
    db["visitors"].update_one(
        {"domainId": payload.domainId, "visitorId": visitor_id},
        {
            "$setOnInsert": {
                "domainId": payload.domainId,
                "visitorId": visitor_id,
                "firstSeenAt": timestamp,
                "pageViewCount": 0,
                "sessionCount": 0,
                "totalActiveMs": 0,
                "sessionIds": [],
            },
            "$set": {
                "lastSeenAt": timestamp,
                "updatedAt": timestamp,
                "lastPageUrl": payload.pageUrl,
                "lastPageTitle": payload.pageTitle,
                "referrer": payload.referrer,
                "userAgent": payload.userAgent,
                "isIdentified": bool(email),
                **({"email": email} if email else {}),
            },
        },
        upsert=True,
    )
    contact_id = None
    if email:
        linked = link_visitor_to_contact(db, payload.domainId, visitor_id, email, payload.properties, payload.pageUrl)
        contact_id = linked.get("contactId")
    return {"ok": True, "visitorId": visitor_id, "contactId": contact_id, "isIdentified": bool(email)}


def upsert_contact(
    db: Database,
    domain_id: str,
    email: str,
    properties: dict[str, Any] | None = None,
    page_url: str | None = None,
) -> dict[str, Any] | None:
    timestamp = now_iso()
    normalized = normalize_email(email)
    if not normalized:
        return None
    return db["contacts"].find_one_and_update(
        {"domainId": domain_id, "email": normalized},
        {
            "$setOnInsert": {
                "domainId": domain_id,
                "email": normalized,
                "isUnsubscribed": False,
                "createdAt": timestamp,
                "properties": properties or {},
            },
            "$set": {
                "updatedAt": timestamp,
                "lastWebsiteVisitAt": timestamp,
                **({"lastWebsitePageUrl": page_url} if page_url else {}),
            },
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )


def link_visitor_to_contact(
    db: Database,
    domain_id: str,
    visitor_id: str,
    email: str,
    properties: dict[str, Any] | None = None,
    page_url: str | None = None,
) -> dict[str, Any]:
    contact = upsert_contact(db, domain_id, email, properties, page_url)
    contact_id = str(contact["_id"]) if contact and contact.get("_id") else None
    db["visitors"].update_one(
        {"domainId": domain_id, "visitorId": visitor_id},
        {
            "$set": {
                "email": normalize_email(email),
                "contactId": contact_id,
                "isIdentified": True,
                "identifiedAt": now_iso(),
                "updatedAt": now_iso(),
            }
        },
    )
    return {"contact": contact, "contactId": contact_id}


@app.post("/track/identify")
def identify_visitor(payload: IdentifyRequest) -> dict[str, Any]:
    linked = link_visitor_to_contact(get_db(), payload.domainId, payload.visitorId, str(payload.email), payload.properties)
    return {"ok": True, "visitorId": payload.visitorId, "contactId": linked.get("contactId"), "email": normalize_email(str(payload.email))}


@app.post("/track/events/batch")
def track_events_batch(payload: BatchRequest) -> dict[str, Any]:
    db = get_db()
    created_at = now_iso()
    visitor_cache: dict[str, dict[str, Any]] = {}
    docs: list[dict[str, Any]] = []
    for event in payload.events:
        visitor_key = f"{event.domainId}:{event.visitorId}"
        visitor = visitor_cache.get(visitor_key)
        if visitor is None:
            visitor = db["visitors"].find_one({"domainId": event.domainId, "visitorId": event.visitorId}) or {}
            visitor_cache[visitor_key] = visitor
        if not visitor:
            db["visitors"].update_one(
                {"domainId": event.domainId, "visitorId": event.visitorId},
                {
                    "$setOnInsert": {
                        "domainId": event.domainId,
                        "visitorId": event.visitorId,
                        "firstSeenAt": created_at,
                        "pageViewCount": 0,
                        "sessionCount": 0,
                        "totalActiveMs": 0,
                        "sessionIds": [],
                        "isIdentified": False,
                    },
                    "$set": {"lastSeenAt": created_at, "updatedAt": created_at},
                },
                upsert=True,
            )
            visitor = db["visitors"].find_one({"domainId": event.domainId, "visitorId": event.visitorId}) or {}
            visitor_cache[visitor_key] = visitor
        if event.eventType == "form_submit":
            email = normalize_email(str(event.metadata.get("email", "")))
            if email:
                linked = link_visitor_to_contact(db, event.domainId, event.visitorId, email, event.metadata, event.pageUrl)
                visitor = {**visitor, "contactId": linked.get("contactId"), "email": email, "isIdentified": True}
                visitor_cache[visitor_key] = visitor
        timestamp = safe_timestamp(event.timestamp)
        update: dict[str, Any] = {
            "$set": {
                "lastSeenAt": timestamp,
                "updatedAt": created_at,
                "lastPageUrl": event.pageUrl,
                "lastPageTitle": event.pageTitle,
            }
        }
        inc: dict[str, int] = {}
        if event.eventType == "page_view":
            inc["pageViewCount"] = 1
        if event.eventType == "time_on_page":
            inc["totalActiveMs"] = active_ms_delta(event.metadata)
        if inc:
            update["$inc"] = inc
        known_sessions = visitor.get("sessionIds") or []
        if event.sessionId and event.sessionId not in known_sessions:
            update["$addToSet"] = {"sessionIds": event.sessionId}
            update.setdefault("$inc", {})["sessionCount"] = 1
            visitor["sessionIds"] = [*known_sessions, event.sessionId]
            visitor_cache[visitor_key] = visitor
        db["visitors"].update_one({"domainId": event.domainId, "visitorId": event.visitorId}, update)
        if visitor.get("contactId"):
            contact_set: dict[str, Any] = {
                "updatedAt": created_at,
                "lastWebsiteVisitAt": timestamp,
                "lastWebsitePageUrl": event.pageUrl,
                "lastWebsitePageTitle": event.pageTitle,
            }
            contact_inc: dict[str, int] = {}
            if event.eventType == "page_view":
                contact_inc["pageViewCount"] = 1
            if event.eventType == "time_on_page":
                contact_inc["totalActiveMs"] = active_ms_delta(event.metadata)
            if event.sessionId and event.sessionId not in known_sessions:
                contact_inc["sessionCount"] = 1
            update_doc: dict[str, Any] = {"$set": contact_set}
            if contact_inc:
                update_doc["$inc"] = contact_inc
            if isinstance(visitor.get("contactId"), str) and ObjectId.is_valid(visitor["contactId"]):
                db["contacts"].update_one({"_id": ObjectId(visitor["contactId"]), "domainId": event.domainId}, update_doc)
            elif visitor.get("email"):
                db["contacts"].update_one({"domainId": event.domainId, "email": visitor["email"]}, update_doc)
        docs.append(
            {
                "domainId": event.domainId,
                "visitorId": event.visitorId,
                "contactId": visitor.get("contactId"),
                "sessionId": event.sessionId,
                "eventType": event.eventType,
                "pageUrl": event.pageUrl,
                "pageTitle": event.pageTitle,
                "referrer": event.referrer,
                "metadata": event.metadata,
                "timestamp": timestamp,
                "createdAt": created_at,
            }
        )
    if docs:
        db["visitor_events"].insert_many(docs, ordered=False)
    return {"ok": True, "accepted": len(payload.events), "created": len(docs)}


@app.get("/track/visitors")
def list_visitors(domainId: str | None = Query(default=None)) -> dict[str, Any]:
    query = {"domainId": domainId} if domainId else {}
    visitors = list(get_db()["visitors"].find(query).sort("lastSeenAt", -1).limit(50))
    for visitor in visitors:
        if visitor.get("_id"):
            visitor["_id"] = str(visitor["_id"])
    return {"ok": True, "visitors": visitors}


@app.get("/track/events")
def list_track_events(domainId: str | None = Query(default=None), visitorId: str | None = Query(default=None)) -> dict[str, Any]:
    query: dict[str, Any] = {}
    if domainId:
        query["domainId"] = domainId
    if visitorId:
        query["visitorId"] = visitorId
    events = list(get_db()["visitor_events"].find(query).sort("timestamp", -1).limit(100))
    for event in events:
        if event.get("_id"):
            event["_id"] = str(event["_id"])
    return {"ok": True, "events": events}


@app.get("/contacts")
def list_contacts(domainId: str | None = Query(default=None), search: str | None = Query(default=None)) -> dict[str, Any]:
    query: dict[str, Any] = {}
    if domainId:
        query["domainId"] = domainId
    if search:
        query["$or"] = [
            {"email": {"$regex": search, "$options": "i"}},
            {"firstName": {"$regex": search, "$options": "i"}},
            {"lastName": {"$regex": search, "$options": "i"}},
            {"company": {"$regex": search, "$options": "i"}},
        ]
    contacts = list(get_db()["contacts"].find(query).sort("updatedAt", -1).limit(100))
    return {"ok": True, "contacts": [public_contact(contact) for contact in contacts]}


@app.get("/contacts/{contact_id}")
def get_contact(contact_id: str) -> dict[str, Any]:
    contact_object_id = object_id_from(contact_id)
    if not contact_object_id:
        raise HTTPException(status_code=400, detail="Invalid contact id")
    contact = get_db()["contacts"].find_one({"_id": contact_object_id})
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    return {"ok": True, "contact": public_contact(contact)}


@app.patch("/contacts/{contact_id}")
def patch_contact(contact_id: str, payload: ContactPatchRequest) -> dict[str, Any]:
    contact_object_id = object_id_from(contact_id)
    if not contact_object_id:
        raise HTTPException(status_code=400, detail="Invalid contact id")
    set_doc: dict[str, Any] = {"updatedAt": now_iso()}
    if payload.firstName is not None:
        set_doc["firstName"] = payload.firstName or None
    if payload.lastName is not None:
        set_doc["lastName"] = payload.lastName or None
    if payload.company is not None:
        set_doc["company"] = payload.company or None
    if payload.properties:
        for key, value in payload.properties.items():
            set_doc[f"properties.{key}"] = value
    contact = get_db()["contacts"].find_one_and_update(
        {"_id": contact_object_id},
        {"$set": set_doc},
        return_document=ReturnDocument.AFTER,
    )
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    return {"ok": True, "contact": public_contact(contact)}


@app.get("/contacts/{contact_id}/activity")
def contact_activity(contact_id: str) -> dict[str, Any]:
    db = get_db()
    contact_object_id = object_id_from(contact_id)
    if not contact_object_id:
        raise HTTPException(status_code=400, detail="Invalid contact id")
    contact = db["contacts"].find_one({"_id": contact_object_id})
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    contact_id_string = str(contact["_id"])
    visitors = list(db["visitors"].find({"contactId": contact_id_string}).sort("lastSeenAt", -1))
    visitor_ids = [item.get("visitorId") for item in visitors if item.get("visitorId")]
    event_query: dict[str, Any]
    if visitor_ids:
        event_query = {"domainId": contact.get("domainId"), "$or": [{"contactId": contact_id_string}, {"visitorId": {"$in": visitor_ids}}]}
    else:
        event_query = {"domainId": contact.get("domainId"), "contactId": contact_id_string}
    website_events = list(db["visitor_events"].find(event_query).sort("timestamp", -1).limit(200))
    email_events = list(db["email_events"].find({"domainId": contact.get("domainId"), "contactId": contact_id_string}).sort("timestamp", -1).limit(100))
    page_counts = top_pages_from_signals(website_events)
    timeline = [
        {
            "id": str(event.get("_id")) if event.get("_id") else None,
            "source": "website",
            "type": event.get("eventType"),
            "visitorId": event.get("visitorId"),
            "sessionId": event.get("sessionId"),
            "pageUrl": event.get("pageUrl"),
            "pageTitle": event.get("pageTitle"),
            "subject": None,
            "targetUrl": None,
            "metadata": event.get("metadata") or {},
            "timestamp": event.get("timestamp"),
        }
        for event in website_events
    ] + [
        {
            "id": str(event.get("_id")) if event.get("_id") else None,
            "source": "email",
            "type": event.get("eventType"),
            "visitorId": None,
            "sessionId": None,
            "pageUrl": None,
            "pageTitle": None,
            "subject": event.get("subject"),
            "targetUrl": event.get("targetUrl"),
            "metadata": event.get("metadata") or {},
            "timestamp": event.get("timestamp"),
        }
        for event in email_events
    ]
    timeline.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
    return {
        "ok": True,
        "contact": public_contact(contact),
        "visitors": [
            {
                "id": str(visitor.get("_id")) if visitor.get("_id") else None,
                "visitorId": visitor.get("visitorId"),
                "firstSeenAt": visitor.get("firstSeenAt"),
                "lastSeenAt": visitor.get("lastSeenAt"),
                "pageViewCount": int(visitor.get("pageViewCount") or 0),
                "sessionCount": int(visitor.get("sessionCount") or 0),
                "totalActiveMs": int(visitor.get("totalActiveMs") or 0),
            }
            for visitor in visitors
        ],
        "summary": {
            "websiteEventCount": len(website_events),
            "emailEventCount": len(email_events),
            "visitorCount": len(visitors),
            "topPages": page_counts,
        },
        "timeline": timeline,
    }


@app.post("/emails/send")
def send_email(payload: SendEmailRequest, request: Request) -> dict[str, Any]:
    try:
        message = send_tracked_email(
            get_db(),
            domain_id=payload.domainId,
            contact_id=payload.contactId,
            to=str(payload.to),
            from_email=str(payload.from_) if payload.from_ else None,
            subject=payload.subject,
            html=payload.html,
            text=payload.text,
            metadata=payload.metadata,
            request_meta={"userAgent": request.headers.get("user-agent"), "ip": request.client.host if request.client else None},
        )
    except ValueError as error:
        raise HTTPException(status_code=500, detail=str(error))
    return {"ok": True, "message": message}


@app.get("/email/open/{tracking_id}.gif")
def email_open(tracking_id: str, request: Request) -> Response:
    db = get_db()
    timestamp = now_iso()
    message = db["outbound_messages"].find_one({"trackingId": tracking_id})
    if message:
        db["email_events"].insert_one(
            {
                "domainId": message.get("domainId"),
                "contactId": message.get("contactId"),
                "messageId": str(message.get("_id")) if message.get("_id") else None,
                "trackingId": tracking_id,
                "eventType": "open",
                "subject": message.get("subject"),
                "targetUrl": None,
                "userAgent": request.headers.get("user-agent"),
                "ip": request.client.host if request.client else None,
                "metadata": {},
                "timestamp": timestamp,
                "createdAt": timestamp,
            }
        )
        db["outbound_messages"].update_one({"_id": message["_id"]}, {"$set": {"updatedAt": timestamp, "lastOpenedAt": timestamp}, "$inc": {"openCount": 1}})
        if message.get("contactId") and ObjectId.is_valid(message["contactId"]):
            db["contacts"].update_one({"_id": ObjectId(message["contactId"])}, {"$set": {"updatedAt": timestamp, "lastEmailOpenedAt": timestamp}, "$inc": {"emailOpenCount": 1}})
    return Response(content=TRANSPARENT_GIF, media_type="image/gif", headers={"Cache-Control": "no-store, no-cache, must-revalidate, proxy-revalidate"})


@app.get("/email/click/{tracking_id}")
def email_click(tracking_id: str, u: str | None = Query(default=None), request: Request | None = None) -> RedirectResponse:
    db = get_db()
    redirect_url = u or settings.web_origin
    timestamp = now_iso()
    message = db["outbound_messages"].find_one({"trackingId": tracking_id})
    if message:
        db["email_events"].insert_one(
            {
                "domainId": message.get("domainId"),
                "contactId": message.get("contactId"),
                "messageId": str(message.get("_id")) if message.get("_id") else None,
                "trackingId": tracking_id,
                "eventType": "click",
                "subject": message.get("subject"),
                "targetUrl": redirect_url,
                "userAgent": request.headers.get("user-agent") if request else None,
                "ip": request.client.host if request and request.client else None,
                "metadata": {},
                "timestamp": timestamp,
                "createdAt": timestamp,
            }
        )
        db["outbound_messages"].update_one({"_id": message["_id"]}, {"$set": {"updatedAt": timestamp, "lastClickedAt": timestamp}, "$inc": {"clickCount": 1}})
        if message.get("contactId") and ObjectId.is_valid(message["contactId"]):
            db["contacts"].update_one({"_id": ObjectId(message["contactId"])}, {"$set": {"updatedAt": timestamp, "lastEmailClickedAt": timestamp}, "$inc": {"emailClickCount": 1}})
    return RedirectResponse(url=redirect_url, status_code=302)


@app.get("/emails/messages")
def list_email_messages(domainId: str | None = Query(default=None), contactId: str | None = Query(default=None)) -> dict[str, Any]:
    query: dict[str, Any] = {}
    if domainId:
        query["domainId"] = domainId
    if contactId:
        query["contactId"] = contactId
    messages = list(get_db()["outbound_messages"].find(query, {"html": 0, "trackedHtml": 0}).sort("createdAt", -1).limit(100))
    for message in messages:
        if message.get("_id"):
            message["_id"] = str(message["_id"])
    return {"ok": True, "messages": messages}


@app.get("/emails/events")
def list_email_events(domainId: str | None = Query(default=None), contactId: str | None = Query(default=None)) -> dict[str, Any]:
    query: dict[str, Any] = {}
    if domainId:
        query["domainId"] = domainId
    if contactId:
        query["contactId"] = contactId
    events = list(get_db()["email_events"].find(query).sort("timestamp", -1).limit(100))
    for event in events:
        if event.get("_id"):
            event["_id"] = str(event["_id"])
    return {"ok": True, "events": events}


@app.post("/engagement/runs")
def create_engagement_run(payload: CreateEngagementRunRequest) -> dict[str, Any]:
    db = get_db()
    contact_object_id = object_id_from(payload.contactId)
    if not contact_object_id:
        raise HTTPException(status_code=400, detail="Invalid contact id")
    contact = db["contacts"].find_one({"_id": contact_object_id, "domainId": payload.domainId})
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    run_id = os.urandom(8).hex()
    timestamp = now_iso()
    goal = payload.goal or DEFAULT_GOAL
    run = {
        "id": run_id,
        "name": payload.name or normalize_run_name(contact, goal),
        "goal": goal,
        "domainId": payload.domainId,
        "contactId": payload.contactId,
        "autonomyMode": payload.autonomyMode or "guardrailed",
        "status": "running",
        "enrolledCount": 1,
        "confidenceThreshold": clamp(payload.confidenceThreshold or DEFAULT_CONFIDENCE_THRESHOLD, 0, 100),
        "contextDomain": payload.contextDomain,
        "businessDescription": payload.businessDescription,
        "escalationMedia": normalize_escalation_media(payload.escalationMedia),
        "escalationRecipientUserIds": string_array(payload.escalationRecipientUserIds),
        "escalationSlackChannelId": payload.escalationSlackChannelId,
        "escalationSlackChannelName": payload.escalationSlackChannelName,
        "escalationTeamsChannel": payload.escalationTeamsChannel,
        "escalationSmsNumber": payload.escalationSmsNumber,
        "signalSources": {
            "websiteTracking": True,
            "emailSignals": True,
            "smsSignals": False,
            "meetingIntelligence": False,
        },
        "analysisStatus": "running",
        "analysisBatchSize": 1,
        "analysisTotalContacts": 1,
        "analysisProcessedContacts": 0,
        "analysisStartedAt": timestamp,
        "analysisCompletedAt": None,
        "analysisError": None,
        "queueItemCount": 0,
        "latestQueueItemId": None,
        "latestIntentScore": None,
        "latestIntentLevel": None,
        "latestRecommendedAction": None,
        "createdAt": timestamp,
        "updatedAt": timestamp,
    }
    db["engagement_runs"].insert_one(run)
    run_engagement_flow(db, run_id)
    created = db["engagement_runs"].find_one({"id": run_id})
    return {"ok": True, "run": public_run(created)}


@app.get("/engagement/runs")
def list_engagement_runs(
    status: EngagementRunStatus | None = Query(default=None),
    domainId: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    db = get_db()
    query: dict[str, Any] = {}
    if status:
        query["status"] = status
    if domainId:
        query["domainId"] = domainId
    items = list(db["engagement_runs"].find(query).sort("createdAt", -1).skip(offset).limit(limit))
    total = db["engagement_runs"].count_documents(query)
    running_count = db["engagement_runs"].count_documents({**query, "status": "running"})
    aggregate = list(db["engagement_runs"].aggregate([{"$match": query}, {"$group": {"_id": None, "enrolledTotal": {"$sum": {"$ifNull": ["$enrolledCount", 0]}}}}]))
    enrolled_total = int(aggregate[0]["enrolledTotal"]) if aggregate else 0
    return {"ok": True, "items": [public_run(item) for item in items], "total": total, "runningCount": running_count, "enrolledTotal": enrolled_total, "limit": limit, "offset": offset}


@app.get("/engagement/runs/{run_id}")
def get_engagement_run(run_id: str) -> dict[str, Any]:
    run = get_db()["engagement_runs"].find_one({"id": run_id})
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"ok": True, "run": public_run(run)}


@app.patch("/engagement/runs/{run_id}")
def patch_engagement_run(run_id: str, payload: UpdateEngagementRunRequest) -> dict[str, Any]:
    db = get_db()
    update: dict[str, Any] = {}
    if payload.name is not None:
        update["name"] = payload.name.strip()
    if payload.goal is not None:
        update["goal"] = payload.goal.strip()
    if payload.status is not None:
        update["status"] = payload.status
    if payload.autonomyMode is not None:
        update["autonomyMode"] = payload.autonomyMode
    if payload.confidenceThreshold is not None:
        update["confidenceThreshold"] = clamp(payload.confidenceThreshold, 0, 100)
    if payload.escalationMedia is not None:
        update["escalationMedia"] = normalize_escalation_media(payload.escalationMedia)
    if payload.escalationRecipientUserIds is not None:
        update["escalationRecipientUserIds"] = string_array(payload.escalationRecipientUserIds)
    if payload.escalationSlackChannelId is not None:
        update["escalationSlackChannelId"] = payload.escalationSlackChannelId.strip() or None
    if payload.escalationSlackChannelName is not None:
        update["escalationSlackChannelName"] = payload.escalationSlackChannelName.strip() or None
    if payload.escalationTeamsChannel is not None:
        update["escalationTeamsChannel"] = payload.escalationTeamsChannel.strip() or None
    if payload.escalationSmsNumber is not None:
        update["escalationSmsNumber"] = payload.escalationSmsNumber.strip() or None
    if update:
        update_run(db, run_id, update)
    run = db["engagement_runs"].find_one({"id": run_id})
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"ok": True, "run": public_run(run)}


@app.get("/engagement/runs/{run_id}/queue")
def list_engagement_queue(
    run_id: str,
    status: EngagementQueueStatus | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    db = get_db()
    if not db["engagement_runs"].find_one({"id": run_id}):
        raise HTTPException(status_code=404, detail="Run not found")
    query: dict[str, Any] = {"runId": run_id}
    if status:
        query["status"] = status
    items = list(db["engagement_queue"].find(query).sort("createdAt", -1).skip(offset).limit(limit))
    return {"ok": True, "items": [public_queue_item(item) for item in items], "limit": limit, "offset": offset}


@app.get("/engagement/runs/{run_id}/queue/{queue_item_id}")
def get_engagement_queue_item(run_id: str, queue_item_id: str) -> dict[str, Any]:
    item = get_db()["engagement_queue"].find_one({"runId": run_id, "id": queue_item_id})
    if not item:
        raise HTTPException(status_code=404, detail="Queue item not found")
    return {"ok": True, "item": public_queue_item(item)}


@app.post("/engagement/runs/{run_id}/queue/{queue_item_id}/approve")
def approve_engagement_queue_item(run_id: str, queue_item_id: str) -> dict[str, Any]:
    item = approve_queue_item(get_db(), run_id, queue_item_id)
    return {"ok": True, "item": public_queue_item(item)}


@app.post("/engagement/runs/{run_id}/queue/{queue_item_id}/pause")
def pause_engagement_queue_item(run_id: str, queue_item_id: str) -> dict[str, Any]:
    item = pause_queue_item(get_db(), run_id, queue_item_id)
    return {"ok": True, "item": public_queue_item(item)}


@app.post("/engagement/runs/{run_id}/queue/{queue_item_id}/generate-message")
def generate_engagement_message(run_id: str, queue_item_id: str, payload: GenerateMessageRequest) -> dict[str, Any]:
    item = generate_queue_item_message(get_db(), run_id, queue_item_id, payload.regenerate)
    return {"ok": True, "item": public_queue_item(item)}


@app.put("/engagement/runs/{run_id}/queue/{queue_item_id}/message")
def save_engagement_message(run_id: str, queue_item_id: str, payload: SaveMessageRequest) -> dict[str, Any]:
    item = save_queue_item_message(get_db(), run_id, queue_item_id, payload)
    return {"ok": True, "item": public_queue_item(item)}


@app.get("/engagement/runs/{run_id}/decision-traces")
def list_engagement_decision_traces(
    run_id: str,
    contactId: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    db = get_db()
    if not db["engagement_runs"].find_one({"id": run_id}):
        raise HTTPException(status_code=404, detail="Run not found")
    query: dict[str, Any] = {"runId": run_id}
    if contactId:
        query["contactId"] = contactId
    traces = list(db["agent_decision_traces"].find(query).sort("createdAt", -1).skip(offset).limit(limit))
    return {"ok": True, "items": [public_trace(trace) for trace in traces], "limit": limit, "offset": offset}


@app.get("/engagement/runs/{run_id}/graph")
def get_engagement_graph(run_id: str) -> dict[str, Any]:
    db = get_db()
    run = db["engagement_runs"].find_one({"id": run_id})
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    queue = list(db["engagement_queue"].find({"runId": run_id}).sort("createdAt", -1).limit(10))
    traces = list(db["agent_decision_traces"].find({"runId": run_id}).sort("createdAt", -1).limit(20))
    return {"ok": True, "run": public_run(run), "queue": [public_queue_item(item) for item in queue], "traces": [public_trace(trace) for trace in traces]}


@app.get("/engagement/runs/{run_id}/notifications")
def get_engagement_notifications(
    run_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    db = get_db()
    if not db["engagement_runs"].find_one({"id": run_id}):
        raise HTTPException(status_code=404, detail="Run not found")
    items = list(db["engagement_notifications"].find({"runId": run_id}).sort("createdAt", -1).skip(offset).limit(limit))
    return {"ok": True, "items": [public_notification(item) for item in items], "limit": limit, "offset": offset}

