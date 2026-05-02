import React, { FormEvent, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

declare global {
  interface Window {
    CRM247?: {
      track: (eventType: string, metadata?: Record<string, unknown>) => void;
      identify: (email: string, properties?: Record<string, unknown>) => Promise<unknown>;
      flush: () => void;
      getState: () => Record<string, unknown>;
    };
  }
}

const API_ORIGIN = import.meta.env.VITE_API_ORIGIN || "http://localhost:8080";
const DEMO_DOMAIN_ID = "demo-store";

interface VisitorRow {
  visitorId: string;
  email?: string;
  isIdentified?: boolean;
  pageViewCount?: number;
  sessionCount?: number;
  totalActiveMs?: number;
  lastSeenAt?: string;
}

interface EventRow {
  _id?: string;
  visitorId: string;
  eventType: string;
  pageUrl: string;
  pageTitle?: string;
  timestamp: string;
  metadata?: Record<string, unknown>;
}

interface ContactRow {
  id: string;
  domainId: string;
  email: string;
  firstName?: string | null;
  lastName?: string | null;
  company?: string | null;
  pageViewCount?: number;
  sessionCount?: number;
  lastWebsiteVisitAt?: string | null;
}

interface ContactActivity {
  summary: {
    websiteEventCount: number;
    visitorCount: number;
    topPages: Array<{ pageUrl: string; pageTitle?: string | null; count: number }>;
  };
  timeline: Array<{
    id: string;
    source: string;
    type: string;
    pageUrl: string;
    pageTitle?: string | null;
    timestamp: string;
  }>;
}

function App() {
  const [trackerState, setTrackerState] = useState<Record<string, unknown> | null>(null);
  const [email, setEmail] = useState("demo@crm247.local");
  const [visitors, setVisitors] = useState<VisitorRow[]>([]);
  const [events, setEvents] = useState<EventRow[]>([]);
  const [contacts, setContacts] = useState<ContactRow[]>([]);
  const [selectedContactId, setSelectedContactId] = useState<string | null>(null);
  const [contactActivity, setContactActivity] = useState<ContactActivity | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);

  const refreshTrackerState = () => {
    setTrackerState(window.CRM247?.getState() || null);
  };

  const refreshData = async () => {
    try {
      setApiError(null);
      const [visitorsRes, eventsRes, contactsRes] = await Promise.all([
        fetch(`${API_ORIGIN}/track/visitors?domainId=${encodeURIComponent(DEMO_DOMAIN_ID)}`),
        fetch(`${API_ORIGIN}/track/events?domainId=${encodeURIComponent(DEMO_DOMAIN_ID)}`),
        fetch(`${API_ORIGIN}/contacts?domainId=${encodeURIComponent(DEMO_DOMAIN_ID)}`)
      ]);
      if (!visitorsRes.ok || !eventsRes.ok || !contactsRes.ok) {
        throw new Error("Tracking API is not ready yet.");
      }
      const visitorsJson = await visitorsRes.json();
      const eventsJson = await eventsRes.json();
      const contactsJson = await contactsRes.json();
      setVisitors(visitorsJson.visitors || []);
      setEvents(eventsJson.events || []);
      const nextContacts = contactsJson.contacts || [];
      setContacts(nextContacts);
      setSelectedContactId((current) => current || nextContacts[0]?.id || null);
      refreshTrackerState();
    } catch (error) {
      setApiError(error instanceof Error ? error.message : "Unable to load tracking data.");
    }
  };

  const loadContactActivity = async (contactId: string | null) => {
    if (!contactId) {
      setContactActivity(null);
      return;
    }
    try {
      const response = await fetch(`${API_ORIGIN}/contacts/${contactId}/activity`);
      if (!response.ok) throw new Error("Unable to load contact activity.");
      const json = await response.json();
      setContactActivity({
        summary: json.summary,
        timeline: json.timeline || []
      });
    } catch {
      setContactActivity(null);
    }
  };

  useEffect(() => {
    const existing = document.querySelector(`script[data-crm247-id="${DEMO_DOMAIN_ID}"]`);
    if (existing) return;

    const script = document.createElement("script");
    script.src = `${API_ORIGIN}/tracker/${DEMO_DOMAIN_ID}.js`;
    script.defer = true;
    script.dataset.crm247Id = DEMO_DOMAIN_ID;
    script.onload = () => {
      window.setTimeout(() => {
        refreshTrackerState();
        void refreshData();
      }, 600);
    };
    document.head.appendChild(script);

    const timer = window.setInterval(refreshTrackerState, 1500);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    void loadContactActivity(selectedContactId);
  }, [selectedContactId]);

  const trackDemoEvent = (eventType: string, metadata: Record<string, unknown>) => {
    window.CRM247?.track(eventType, metadata);
    window.CRM247?.flush();
    window.setTimeout(() => void refreshData(), 600);
  };

  const handleIdentify = async (event: FormEvent) => {
    event.preventDefault();
    if (!email.trim()) return;
    await window.CRM247?.identify(email.trim(), {
      source: "demo_form",
      plan: "hackathon"
    });
    window.CRM247?.flush();
    window.setTimeout(() => void refreshData(), 800);
  };

  return (
    <main className="shell">
      <section className="hero">
        <div>
          <p className="eyebrow">MongoDB Agentic Evolution Hackathon</p>
          <h1>crm247</h1>
          <p className="lede">
            Multi-agent autonomous engagement powered by cookie tracking,
            email engagement, LangGraph, and MongoDB Atlas.
          </p>
        </div>
        <div className="status">
          <span>Phase 2</span>
          <strong>Cookie tracking</strong>
          <small>{trackerState ? "Tracker loaded" : "Waiting for tracker"}</small>
        </div>
      </section>

      <section className="demo-grid">
        <article className="panel primary-panel">
          <h2>Demo Product Page</h2>
          <p>
            This page loads the generated tracker from the API. Use these actions
            to create page, click, form, and custom engagement events.
          </p>
          <div className="actions">
            <button
              type="button"
              data-track-id="view-product"
              onClick={() =>
                trackDemoEvent("custom", {
                  name: "product_interest",
                  product: "Atlas Agent Console",
                  value: 149
                })
              }
            >
              View product
            </button>
            <button
              type="button"
              data-track-id="start-checkout"
              onClick={() =>
                trackDemoEvent("custom", {
                  name: "checkout_started",
                  product: "Atlas Agent Console"
                })
              }
            >
              Start checkout
            </button>
            <button
              type="button"
              data-track-id="pricing-click"
              onClick={() =>
                trackDemoEvent("click", {
                  cta: "pricing",
                  intent: "high"
                })
              }
            >
              Pricing CTA
            </button>
          </div>

          <form className="identify-form" onSubmit={handleIdentify}>
            <label htmlFor="email">Identify visitor</label>
            <div>
              <input
                id="email"
                name="email"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="customer@example.com"
              />
              <button type="submit">Identify</button>
            </div>
          </form>
        </article>

        <article className="panel">
          <h2>Tracker State</h2>
          <pre>{JSON.stringify(trackerState || { status: "not_loaded" }, null, 2)}</pre>
          <button type="button" className="secondary" onClick={() => void refreshData()}>
            Refresh Mongo data
          </button>
          {apiError && <p className="error">{apiError}</p>}
        </article>

        <article className="panel table-panel">
          <h2>Recent Visitors</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Visitor</th>
                  <th>Email</th>
                  <th>Views</th>
                  <th>Sessions</th>
                </tr>
              </thead>
              <tbody>
                {visitors.length === 0 ? (
                  <tr>
                    <td colSpan={4}>No visitors yet.</td>
                  </tr>
                ) : (
                  visitors.map((visitor) => (
                    <tr key={visitor.visitorId}>
                      <td>{visitor.visitorId.slice(0, 18)}...</td>
                      <td>{visitor.email || (visitor.isIdentified ? "identified" : "anonymous")}</td>
                      <td>{visitor.pageViewCount || 0}</td>
                      <td>{visitor.sessionCount || 0}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </article>

        <article className="panel table-panel">
          <h2>Recent Events</h2>
          <div className="event-list">
            {events.length === 0 ? (
              <p>No events yet.</p>
            ) : (
              events.slice(0, 12).map((event) => (
                <div className="event-row" key={event._id || `${event.visitorId}-${event.timestamp}`}>
                  <strong>{event.eventType}</strong>
                  <span>{new Date(event.timestamp).toLocaleTimeString()}</span>
                  <small>{event.pageTitle || event.pageUrl}</small>
                </div>
              ))
            )}
          </div>
        </article>

        <article className="panel table-panel">
          <h2>Identified Contacts</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Email</th>
                  <th>Views</th>
                  <th>Sessions</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {contacts.length === 0 ? (
                  <tr>
                    <td colSpan={4}>No identified contacts yet.</td>
                  </tr>
                ) : (
                  contacts.map((contact) => (
                    <tr key={contact.id} className={selectedContactId === contact.id ? "selected-row" : ""}>
                      <td>{contact.email}</td>
                      <td>{contact.pageViewCount || 0}</td>
                      <td>{contact.sessionCount || 0}</td>
                      <td>
                        <button
                          type="button"
                          className="small-button"
                          onClick={() => setSelectedContactId(contact.id)}
                        >
                          Activity
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </article>

        <article className="panel table-panel">
          <h2>Contact Activity</h2>
          {!selectedContactId ? (
            <p>Select an identified contact to inspect the linked website timeline.</p>
          ) : !contactActivity ? (
            <p>No linked activity loaded yet.</p>
          ) : (
            <>
              <div className="summary-strip">
                <span>{contactActivity.summary.websiteEventCount} events</span>
                <span>{contactActivity.summary.visitorCount} visitor ids</span>
              </div>
              <div className="top-pages">
                {contactActivity.summary.topPages.length === 0 ? (
                  <p>No page views linked to this contact.</p>
                ) : (
                  contactActivity.summary.topPages.map((page) => (
                    <div key={page.pageUrl}>
                      <strong>{page.pageTitle || page.pageUrl}</strong>
                      <span>{page.count} views</span>
                    </div>
                  ))
                )}
              </div>
              <div className="event-list compact-list">
                {contactActivity.timeline.slice(0, 10).map((event) => (
                  <div className="event-row" key={event.id}>
                    <strong>{event.type}</strong>
                    <span>{new Date(event.timestamp).toLocaleTimeString()}</span>
                    <small>{event.pageTitle || event.pageUrl}</small>
                  </div>
                ))}
              </div>
            </>
          )}
        </article>
      </section>
    </main>
  );
}

createRoot(document.getElementById("root") as HTMLElement).render(<App />);
