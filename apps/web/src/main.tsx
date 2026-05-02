import React from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

function App() {
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
          <span>Phase 1</span>
          <strong>Foundation ready</strong>
        </div>
      </section>

      <section className="grid">
        <article>
          <h2>Cookie Tracking</h2>
          <p>Next phase: first-party visitor ID, sessions, and batched website events.</p>
        </article>
        <article>
          <h2>Email Tracking</h2>
          <p>Open pixels, click redirects, outbound message records, and contact timelines.</p>
        </article>
        <article>
          <h2>LangGraph Agents</h2>
          <p>Supervisor, signal, intent, retrieval, strategy, message, policy, delivery, and learning agents.</p>
        </article>
        <article>
          <h2>MongoDB Atlas</h2>
          <p>Shared context, checkpoints, decision traces, queue state, and adaptive memory.</p>
        </article>
      </section>
    </main>
  );
}

createRoot(document.getElementById("root") as HTMLElement).render(<App />);

