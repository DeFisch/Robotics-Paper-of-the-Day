"use strict";

const state = { papers: [], updated: null };

async function load() {
  try {
    const res = await fetch("./data/papers.json", { cache: "no-store" });
    const data = await res.json();
    state.papers = data.papers || [];
    state.updated = data.updated;
  } catch (e) {
    state.papers = [];
  }
  initControls();
  render();
}

function initControls() {
  const topics = new Set();
  state.papers.forEach((p) => (p.topic_tags || []).forEach((t) => topics.add(t)));
  const sel = document.getElementById("topic");
  [...topics].sort().forEach((t) => {
    const o = document.createElement("option");
    o.value = o.textContent = t;
    sel.appendChild(o);
  });
  ["search", "topic", "reputableOnly", "sort"].forEach((id) =>
    document.getElementById(id).addEventListener("input", render)
  );

  const meta = document.getElementById("meta");
  if (state.updated) {
    const d = new Date(state.updated);
    meta.textContent = `${state.papers.length} papers · last updated ${d.toLocaleString()}`;
  } else {
    meta.textContent = "Not yet run — the first batch will appear after the daily job runs.";
  }
}

function escapeHTML(s) {
  return (s || "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function filtered() {
  const q = document.getElementById("search").value.trim().toLowerCase();
  const topic = document.getElementById("topic").value;
  const repOnly = document.getElementById("reputableOnly").checked;
  const sort = document.getElementById("sort").value;

  let list = state.papers.filter((p) => {
    if (topic && !(p.topic_tags || []).includes(topic)) return false;
    if (repOnly && !(p.reputation && p.reputation.reputable)) return false;
    if (q) {
      const hay = `${p.title} ${(p.authors || []).join(" ")} ${p.abstract}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  const sc = (p, k) => (p.scores && p.scores[k]) || 0;
  if (sort === "relevance") list.sort((a, b) => sc(b, "relevance") - sc(a, "relevance"));
  else if (sort === "quality") list.sort((a, b) => sc(b, "quality") - sc(a, "quality"));
  else list.sort((a, b) => (a.published < b.published ? 1 : -1));
  return list;
}

function card(p) {
  const rep = p.reputation || {};
  const authors = (p.authors || [])
    .map((a) => {
      const isRep = rep.top_author && a === rep.top_author && rep.reputable;
      return isRep ? `<span class="rep">${escapeHTML(a)}★</span>` : escapeHTML(a);
    })
    .slice(0, 10)
    .join(", ");

  const chips = [];
  (p.topic_tags || []).forEach((t) => chips.push(`<span class="chip">${escapeHTML(t)}</span>`));
  if (p.primary_category) chips.push(`<span class="chip cat">${escapeHTML(p.primary_category)}</span>`);
  if (rep.reputable) {
    const detail = rep.max_h_index != null ? `h${rep.max_h_index}` : "known lab";
    chips.push(`<span class="chip rep">reputable · ${detail}</span>`);
  }

  let scores = "";
  if (p.scores) {
    scores = `<span class="scores"><span>rel <b>${p.scores.relevance ?? "-"}</b></span>
      <span>qual <b>${p.scores.quality ?? "-"}</b></span>
      <span>nov <b>${p.scores.novelty ?? "-"}</b></span></span>`;
  }

  const reason = p.scores && p.scores.reason ? `<p class="reason">${escapeHTML(p.scores.reason)}</p>` : "";

  return `<article class="card">
    <h3><a href="${escapeHTML(p.url)}" target="_blank" rel="noopener">${escapeHTML(p.title)}</a></h3>
    <p class="authors">${authors}</p>
    ${reason}
    <div class="chips">${chips.join("")}${scores}</div>
    <button class="toggle">Show abstract ▾</button>
    <p class="abstract">${escapeHTML(p.abstract)} <a href="${escapeHTML(p.pdf)}" target="_blank" rel="noopener">[PDF]</a></p>
  </article>`;
}

function render() {
  const feed = document.getElementById("feed");
  const list = filtered();

  if (!list.length) {
    feed.innerHTML = `<div class="empty"><div class="big">📭</div>
      <p>${state.papers.length ? "No papers match these filters." : "No papers yet. The daily job will populate this feed soon."}</p></div>`;
    return;
  }

  const groups = {};
  list.forEach((p) => (groups[p.published] = groups[p.published] || []).push(p));
  const days = Object.keys(groups).sort().reverse();

  feed.innerHTML = days
    .map((day) => {
      const heading = new Date(day + "T00:00:00").toLocaleDateString(undefined, {
        weekday: "long", year: "numeric", month: "long", day: "numeric",
      });
      return `<section class="day-group"><h2 class="day-heading">${heading}</h2>${groups[day].map(card).join("")}</section>`;
    })
    .join("");

  feed.querySelectorAll(".toggle").forEach((btn) => {
    btn.addEventListener("click", () => {
      const c = btn.closest(".card");
      c.classList.toggle("open");
      btn.textContent = c.classList.contains("open") ? "Hide abstract ▴" : "Show abstract ▾";
    });
  });
}

load();
