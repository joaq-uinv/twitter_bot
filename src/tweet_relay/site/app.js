// Renders status.json (spec 002 plan DD-9). Render-only: every value goes into the
// page through textContent or attributes on elements created here, never as markup
// (FR-17). All arithmetic happened in Python; the one exception is the stale-data
// check, which must be judged when the page is viewed (AC-3.3).
"use strict";

const STALE_AFTER_MS = 12 * 3600 * 1000;
const REASONS = {
  timed_out: "timed out", unreachable: "unreachable", refused_answer: "refused",
  sent_elsewhere: "redirects / bot check", too_large: "too large",
  malformed_content: "not a feed", wrong_account: "wrong account", no_posts: "no posts",
  stale: "stale", refused_address: "refused address",
};

function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (cls) node.className = cls;
  return node;
}

function ago(iso, now) {
  if (!iso) return "never";
  const s = Math.max(0, Math.round((now - Date.parse(iso)) / 1000));
  return age(s) + " ago";
}

function age(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 3600) return Math.round(seconds / 60) + " min";
  if (seconds < 172800) return Math.round(seconds / 3600) + " h";
  return Math.round(seconds / 86400) + " d";
}

function pct(x) {
  return x === null || x === undefined ? "—" : Math.round(x * 100) + "%";
}

function trend(values) {
  const box = el("span", null, "trend");
  box.setAttribute("aria-label", "recent probes, newest last");
  for (const v of values) {
    box.appendChild(el("span", null, v === true ? "t ok" : v === false ? "t bad" : "t none"));
  }
  return box;
}

function table(target, mirrors) {
  target.replaceChildren();
  const head = el("tr");
  for (const h of ["Mirror", "Status", "Response", "Newest post", "7 d", "30 d", "Trend"]) {
    head.appendChild(el("th", h));
  }
  target.appendChild(el("thead")).appendChild(head);
  const body = target.appendChild(el("tbody"));
  if (mirrors.length === 0) {
    const row = body.appendChild(el("tr"));
    const cell = row.appendChild(el("td", "None", "muted"));
    cell.colSpan = 7;
    return;
  }
  for (const m of mirrors) {
    const row = body.appendChild(el("tr"));
    const name = row.appendChild(el("td", m.host, "host"));
    if (m.role === "former") name.appendChild(el("span", "formerly in use", "tag"));
    row.appendChild(el("td", m.healthy ? "healthy" : (REASONS[m.reason] || "unhealthy"),
                       m.healthy ? "ok" : "bad"));
    row.appendChild(el("td", m.ms === null ? "—" : m.ms + " ms"));
    row.appendChild(el("td", age(m.newest_age_s)));
    row.appendChild(el("td", pct(m.uptime_7d)));
    row.appendChild(el("td", pct(m.uptime_30d)));
    row.appendChild(el("td")).appendChild(trend(m.trend || []));
  }
}

function issuesUrl() {
  // Pages lives at https://<owner>.github.io/<repo>/; issues at github.com/<owner>/<repo>.
  const owner = location.hostname.split(".")[0];
  const repo = location.pathname.split("/").filter(Boolean)[0];
  if (!location.hostname.endsWith(".github.io") || !repo) return null;
  return "https://github.com/" + encodeURIComponent(owner) + "/" + encodeURIComponent(repo) +
         "/issues?q=is%3Aissue+is%3Aopen+label%3Amirror-health";
}

function render(s) {
  const now = Date.now();
  const r = s.round;

  const stale = document.getElementById("stale");
  if (now - Date.parse(s.generated_at) > STALE_AFTER_MS) {
    stale.hidden = false;
    stale.textContent = "⚠️ This data is " + ago(s.generated_at, now).replace(" ago", "") +
      " old. The health check may have stopped.";
  }

  const verdict = document.getElementById("verdict");
  if (r.at_risk) {
    verdict.className = "banner risk";
    verdict.textContent = "⚠️ AT RISK: " + r.in_use_healthy + " of " + r.in_use_total +
      " in-use mirrors healthy" + (r.at_risk_since ? " (since " + ago(r.at_risk_since, now) + ")" : "") +
      ". One more failure stops the relay.";
  } else {
    verdict.className = "banner good";
    verdict.textContent = "✅ " + r.in_use_healthy + " of " + r.in_use_total + " in-use mirrors healthy";
  }

  table(document.getElementById("inuse"), s.mirrors.filter((m) => m.role === "in_use"));
  table(document.getElementById("candidates"), s.mirrors.filter((m) => m.role !== "in_use"));

  const section = document.getElementById("warnings-section");
  const list = document.getElementById("warnings");
  list.replaceChildren();
  section.hidden = s.warnings.length === 0;
  for (const w of s.warnings) {
    list.appendChild(el("li", w.host + " — unhealthy for 24 h, open since " + ago(w.since, now)));
  }
  const url = issuesUrl();
  const link = document.getElementById("issues-link");
  if (url && s.warnings.length) {
    link.href = url;
    link.hidden = false;
  }

  const d = s.discovery;
  document.getElementById("discovery").textContent = d.last_ok
    ? "Community list last read " + ago(d.last_ok, now) + ": " + d.accepted + " accepted, " +
      d.rejected + " rejected."
    : "The community list has not been read successfully yet.";

  document.getElementById("generated").textContent =
    "Last probed " + ago(r.t || s.generated_at, now) + " (" + (r.t || s.generated_at) + ").";
}

function fail(message) {
  const verdict = document.getElementById("verdict");
  verdict.className = "banner risk";
  verdict.textContent = message;
}

fetch("status.json", { cache: "no-store" })
  .then((res) => (res.ok ? res.json() : Promise.reject(new Error("HTTP " + res.status))))
  .then(render)
  .catch(() => fail("⚠️ Status data could not be loaded. The health check may not have run yet."));
