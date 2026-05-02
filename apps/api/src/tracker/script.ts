import { config } from "../config.js";

export function buildTrackerScript(domainId: string): string {
  const safeDomainId = JSON.stringify(domainId);
  const fallbackOrigin = JSON.stringify(config.API_ORIGIN);

  return String.raw`(function(window, document) {
  "use strict";

  if (!window || !document) return;

  var COOKIE_NAME = "eg_visitor_id";
  var SESSION_KEY = "crm247.session";
  var DOMAIN_ID = ${safeDomainId};
  var FALLBACK_ORIGIN = ${fallbackOrigin};
  var BATCH_SIZE = 10;
  var BATCH_INTERVAL_MS = 5000;
  var SESSION_TIMEOUT_MS = 30 * 60 * 1000;
  var HEARTBEAT_MS = 15000;

  var state = {
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
  };

  function currentScriptOrigin() {
    try {
      var script = document.currentScript;
      if (!script || !script.src) {
        var scripts = document.getElementsByTagName("script");
        for (var i = scripts.length - 1; i >= 0; i--) {
          if (scripts[i] && scripts[i].src && scripts[i].src.indexOf("/tracker/") !== -1) {
            script = scripts[i];
            break;
          }
        }
      }
      if (script && script.src) return new URL(script.src).origin;
    } catch (error) {}
    return FALLBACK_ORIGIN;
  }

  function endpoint(path) {
    return currentScriptOrigin() + path;
  }

  function makeId(prefix) {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return prefix + "_" + window.crypto.randomUUID();
    }
    return prefix + "_" + Math.random().toString(36).slice(2) + Date.now().toString(36);
  }

  function setCookie(name, value, days) {
    var date = new Date();
    date.setTime(date.getTime() + days * 24 * 60 * 60 * 1000);
    document.cookie = name + "=" + encodeURIComponent(value) + "; expires=" + date.toUTCString() + "; path=/; SameSite=Lax";
  }

  function getCookie(name) {
    var parts = document.cookie ? document.cookie.split(";") : [];
    for (var i = 0; i < parts.length; i++) {
      var part = parts[i].trim();
      if (part.indexOf(name + "=") === 0) {
        return decodeURIComponent(part.substring(name.length + 1));
      }
    }
    return null;
  }

  function readSession() {
    try {
      var raw = window.localStorage.getItem(SESSION_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (error) {
      return null;
    }
  }

  function writeSession(session) {
    try {
      window.localStorage.setItem(SESSION_KEY, JSON.stringify(session));
    } catch (error) {}
  }

  function getSessionId() {
    var now = Date.now();
    var existing = readSession();
    if (existing && existing.id && existing.lastSeenAt && now - existing.lastSeenAt < SESSION_TIMEOUT_MS) {
      existing.lastSeenAt = now;
      writeSession(existing);
      return existing.id;
    }
    var next = { id: makeId("sess"), createdAt: now, lastSeenAt: now };
    writeSession(next);
    return next.id;
  }

  function visitorId() {
    var existing = getCookie(COOKIE_NAME);
    if (existing) return existing;
    var next = makeId("v");
    setCookie(COOKIE_NAME, next, 365);
    return next;
  }

  function postJSON(path, body, keepalive) {
    var payload = JSON.stringify(body);
    if (typeof fetch === "function") {
      return fetch(endpoint(path), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: payload,
        keepalive: !!keepalive,
        credentials: "omit"
      }).then(function(resp) {
        return resp.text().then(function(text) {
          var json = null;
          try { json = text ? JSON.parse(text) : null; } catch (error) {}
          return { ok: resp.ok, status: resp.status, json: json };
        });
      }).catch(function() {
        return { ok: false, status: 0, json: null };
      });
    }
    return Promise.resolve({ ok: false, status: 0, json: null });
  }

  function baseEvent(eventType, metadata) {
    state.eventSeq += 1;
    return {
      domainId: DOMAIN_ID,
      visitorId: state.visitorId,
      sessionId: state.sessionId,
      eventType: eventType,
      pageUrl: window.location.href,
      pageTitle: document.title || "",
      referrer: document.referrer || null,
      timestamp: new Date().toISOString(),
      metadata: Object.assign({
        pageVisitId: state.pageVisitId,
        eventSeq: state.eventSeq,
        sdk: "crm247-js",
        source: "website",
        viewport: {
          width: window.innerWidth || null,
          height: window.innerHeight || null
        }
      }, metadata || {})
    };
  }

  function enqueue(event) {
    state.queue.push(event);
    if (state.queue.length >= BATCH_SIZE) flush(false);
  }

  function flush(useBeacon) {
    if (!state.ready || state.queue.length === 0) return;
    var batch = state.queue.splice(0, state.queue.length);
    var body = { events: batch };
    if (useBeacon && navigator.sendBeacon) {
      try {
        var blob = new Blob([JSON.stringify(body)], { type: "application/json" });
        if (navigator.sendBeacon(endpoint("/track/events/batch"), blob)) return;
      } catch (error) {}
    }
    postJSON("/track/events/batch", body, false).then(function(result) {
      if (!result.ok) state.queue = batch.concat(state.queue);
    });
  }

  function register(email, properties) {
    return postJSON("/track/visitor", {
      domainId: DOMAIN_ID,
      visitorId: state.visitorId,
      sessionId: state.sessionId,
      email: email || null,
      pageUrl: window.location.href,
      pageTitle: document.title || "",
      referrer: document.referrer || null,
      userAgent: navigator.userAgent || null,
      properties: properties || {}
    }, false).then(function(result) {
      state.ready = !!result.ok;
      if (result.json && result.json.visitorId) {
        state.visitorId = result.json.visitorId;
        setCookie(COOKIE_NAME, state.visitorId, 365);
      }
      if (state.ready) flush(false);
      return result;
    });
  }

  function identify(email, properties) {
    if (!email) return Promise.resolve({ ok: false });
    return postJSON("/track/identify", {
      domainId: DOMAIN_ID,
      visitorId: state.visitorId,
      email: email,
      properties: properties || {}
    }, false).then(function(result) {
      register(email, properties || {});
      return result;
    });
  }

  function track(eventType, metadata) {
    enqueue(baseEvent(eventType || "custom", metadata || {}));
  }

  function setupClickTracking() {
    document.addEventListener("click", function(event) {
      var target = event.target;
      if (!target) return;
      var element = target.closest ? target.closest("a,button,[data-track-id]") : target;
      if (!element) return;
      track("click", {
        elementTag: element.tagName || null,
        elementId: element.id || null,
        trackId: element.getAttribute ? element.getAttribute("data-track-id") : null,
        text: element.textContent ? String(element.textContent).trim().slice(0, 160) : null,
        href: element.href || null
      });
    }, true);
  }

  function setupFormTracking() {
    document.addEventListener("submit", function(event) {
      var form = event.target;
      if (!form || form.tagName !== "FORM") return;
      var emailInput = form.querySelector('input[type="email"], input[name="email"]');
      var email = emailInput && emailInput.value ? String(emailInput.value).trim().toLowerCase() : null;
      track("form_submit", {
        formId: form.id || null,
        email: email,
        emailPresent: !!email
      });
      if (email) identify(email, { source: "form_submit" });
    }, true);
  }

  function setupExitIntent() {
    var lastExit = 0;
    document.addEventListener("mouseout", function(event) {
      if (event.relatedTarget || event.toElement) return;
      if (typeof event.clientY === "number" && event.clientY > 12) return;
      var now = Date.now();
      if (now - lastExit < 15000) return;
      if (now - state.pageStartedAt < 3000) return;
      lastExit = now;
      track("exit_intent", { reason: "mouse_top_exit" });
    }, true);
  }

  function startHeartbeat() {
    state.heartbeatTimer = window.setInterval(function() {
      var now = Date.now();
      var delta = now - state.lastActiveSentAt;
      if (delta < 1000) return;
      state.lastActiveSentAt = now;
      track("time_on_page", { activeMsDelta: delta });
    }, HEARTBEAT_MS);
  }

  function init() {
    state.visitorId = visitorId();
    state.sessionId = getSessionId();
    setupClickTracking();
    setupFormTracking();
    setupExitIntent();
    startHeartbeat();
    register(null, {});
    track("page_view", {});
    state.batchTimer = window.setInterval(function() { flush(false); }, BATCH_INTERVAL_MS);
    window.addEventListener("pagehide", function() { flush(true); });
    window.addEventListener("beforeunload", function() { flush(true); });
  }

  window.CRM247 = {
    track: track,
    identify: identify,
    flush: function() { flush(false); },
    getState: function() {
      return {
        domainId: DOMAIN_ID,
        visitorId: state.visitorId,
        sessionId: state.sessionId,
        queueLength: state.queue.length,
        ready: state.ready
      };
    }
  };

  init();
})(window, document);`;
}

