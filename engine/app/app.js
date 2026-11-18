// Job Finder page. Talks only to the small server on this Mac (app_server.py).
"use strict";

const $ = (id) => document.getElementById(id);

// The secret code arrives in the address (#t=...). Keep it for this tab
// and tidy the address bar.
const token = (() => {
  const m = location.hash.match(/t=([\w-]+)/);
  let t = m ? m[1] : null;
  try {
    if (t) sessionStorage.setItem("jf-token", t);
    else t = sessionStorage.getItem("jf-token");
  } catch (_) {}
  if (m) history.replaceState(null, "", location.pathname);
  return t;
})();

let state = null;          // what the server last told us
let polling = null;
let pickedWeek = null;     // a week tile the person clicked (its start date)

async function api(path, body = {}) {
  let res;
  try {
    res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Token": token || "" },
      body: JSON.stringify(body),
    });
  } catch (_) {
    throw new Error("Job Finder was closed. Click Job Finder in your Dock to open it again.");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "Something went wrong.");
  return data;
}

function banner(text) {
  $("banner").textContent = text || "";
  $("banner").hidden = !text;
}

function show(view) {
  for (const v of ["setup", "home", "settings"]) $("view-" + v).hidden = v !== view;
  $("to-settings").hidden = view !== "home";
  $("find").hidden = view !== "home" || !$("find-big").hidden;
  $("to-home").hidden = view !== "settings";
  window.scrollTo(0, 0);
}

// Icons are Lucide (lucide.dev), drawn inline so the app works offline.
const ICONS = {
  arrowUpRight: '<path d="M7 7h10v10"/><path d="M7 17 17 7"/>',
  calendarClock: '<path d="M21 7.5V6a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h3.5"/><path d="M16 2v4"/><path d="M8 2v4"/><path d="M3 10h5"/><path d="M17.5 17.5 16 16.3V14"/><circle cx="16" cy="16" r="6"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  circleAlert: '<circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/>',
  rotateCw: '<path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/>',
  fileText: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>',
  x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
};
function icon(name, size = 14) {
  const t = document.createElement("template");
  t.innerHTML = `<svg class="icon" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name]}</svg>`;
  return t.content.firstChild;
}
function el(tag, className, ...children) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.append(...children.filter((c) => c != null && c !== false && c !== ""));
  return node;
}
function setConnected(node, on) {
  node.replaceChildren(...(on ? [icon("check", 12), "Connected"] : []));
}

// ── Small builders ─────────────────────────────────────────────────

function choiceList(container, name, options, selected) {
  container.innerHTML = "";
  options.forEach(([value, title, sub]) => {
    const label = document.createElement("label");
    label.className = "choice";
    const input = document.createElement("input");
    input.type = "radio";
    input.name = name;
    input.value = value;
    input.checked = String(value) === String(selected);
    const text = document.createElement("div");
    text.innerHTML = "<b></b><span></span>";
    text.firstChild.textContent = title;
    text.lastChild.textContent = sub || "";
    label.append(input, text);
    container.append(label);
  });
}
const chosen = (name) => (document.querySelector(`input[name="${name}"]:checked`) || {}).value;

function levelOptions() {
  return state.levels.map((label, i) => {
    const [title, rest] = label.split(" (");
    return [i + 1, title, rest ? rest.replace(/\)$/, "") : ""];
  });
}
const TRACKERS = [
  ["spreadsheet", "A spreadsheet", "Opens in Excel, Numbers or Google Sheets. Nothing to set up."],
  ["notion", "Notion", "Needs a free Notion account and about 3 minutes."],
];

const splitCities = (text) => text.split(",").map((s) => s.trim()).filter(Boolean);
const titleCase = (s) => s.replace(/\b\w/g, (c) => c.toUpperCase());
const money = (n) => (n ? `${Math.round(n / 1000)}k` : "0");

// ── Companies (shared by setup and settings) ───────────────────────

const companies = { setup: [], settings: [] };   // [{key, slug, name, status, jobs}]
const listEl = { setup: $("setup-companies"), settings: $("set-companies") };

function renderCompanies(where) {
  const ul = listEl[where];
  ul.innerHTML = "";
  companies[where].forEach((c, i) => {
    const li = document.createElement("li");
    li.className = c.status || "found";
    const name = document.createElement("span");
    name.textContent = c.name || c.slug;
    li.append(name);
    const note = { checking: "checking…", missing: "not found", error: "couldn’t check" }[c.status];
    if (note) li.append(el("span", "note", note));
    else if (c.jobs != null) li.append(el("span", "note", icon("check", 11), `${c.jobs} open job${c.jobs === 1 ? "" : "s"}`));
    const x = document.createElement("button");
    x.append(icon("x", 14));
    x.setAttribute("aria-label", `Remove ${c.name || c.slug}`);
    x.onclick = () => { companies[where].splice(i, 1); renderCompanies(where); };
    li.append(x);
    ul.append(li);
  });
  const missing = companies[where].some((c) => c.status === "missing");
  const failed = companies[where].some((c) => c.status === "error");
  let help = ul.nextElementSibling;
  if (!help || !help.classList.contains("chip-help")) {
    help = document.createElement("p");
    help.className = "chip-help";
    ul.after(help);
  }
  help.textContent = [
    missing ? "“Not found” means Job Finder can’t read that company’s careers page. Indeed often lists their jobs anyway, so you may still see them." : "",
    failed ? "“Couldn’t check” means the lookup didn’t finish. Remove the company and add it again to retry." : "",
  ].filter(Boolean).join(" ");
  help.hidden = !(missing || failed);
}

async function addCompanies(where, text) {
  const entries = splitCities(text).map((name) => ({ name, status: "checking" }));
  companies[where].push(...entries);
  renderCompanies(where);
  await Promise.all(entries.map(async (entry) => {
    try {
      const r = await api("/api/company", { name: entry.name });
      Object.assign(entry, r.status === "found"
        ? { status: "found", key: r.key, slug: r.slug, jobs: r.jobs }
        : { status: r.status });
    } catch (e) {
      entry.status = "error";
    }
    renderCompanies(where);
  }));
}
const stillChecking = (where) => companies[where].some((c) => c.status === "checking");

document.querySelectorAll(".company-add").forEach((box) => {
  const where = box.dataset.for;
  const input = box.querySelector("input");
  const go = () => { if (input.value.trim()) { addCompanies(where, input.value); input.value = ""; } };
  box.querySelector("button").onclick = go;
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); go(); } });
});

const companiesForSave = (where) =>
  companies[where].filter((c) => c.key && c.slug).map(({ key, slug }) => ({ key, slug }));

// ── Notion connect panel (shared) ──────────────────────────────────

document.querySelectorAll(".notion-connect").forEach((box) => {
  box.append($("notion-template").content.cloneNode(true));
  const msg = box.querySelector(".n-msg");
  box.querySelector(".n-go").onclick = async (e) => {
    e.target.disabled = true;
    msg.hidden = false;
    msg.className = "n-msg";
    msg.textContent = "Connecting…";
    try {
      const r = await api("/api/notion", {
        token: box.querySelector(".n-token").value,
        link: box.querySelector(".n-link").value,
      });
      msg.className = "n-msg " + (r.ok ? "ok" : "bad");
      if (r.ok) msg.replaceChildren(icon("check", 14), "Connected. A “Job applications” database was added to that page.");
      else msg.textContent = r.message;
      if (r.ok) state.connected = r.connected;
    } catch (err) {
      msg.className = "n-msg bad";
      msg.textContent = err.message;
    }
    e.target.disabled = false;
  };
});

function wireTrackerChoice(container, panel) {
  const update = () => {
    panel.hidden = !(chosen(container.querySelector("input").name) === "notion" && !state.connected.notion);
  };
  container.onchange = update;
  update();
}

// ── First-run questions ────────────────────────────────────────────

let step = 1;
const STEPS = 5;

function startSetup() {
  const s = state.settings;
  choiceList($("setup-level"), "setup-level", levelOptions(), s.level);
  $("setup-cities").value = s.cities.map(titleCase).join(", ");
  $("setup-remote").checked = s.remote;
  $("setup-pay").value = s.min_salary ? money(s.min_salary) : "";
  companies.setup = s.companies.map((c) => ({ ...c, status: "found" }));
  renderCompanies("setup");
  choiceList($("setup-tracker"), "setup-tracker", TRACKERS, s.tracker);
  wireTrackerChoice($("setup-tracker"), document.querySelector('.notion-connect[data-for="setup"]'));
  step = 1;
  showStep();
  show("setup");
}

function showStep() {
  document.querySelectorAll("#view-setup .step").forEach((el) => {
    el.hidden = Number(el.dataset.step) !== step;
  });
  $("step-count").textContent = `${step} of ${STEPS}`;
  $("setup-back").style.visibility = step > 1 ? "visible" : "hidden";
  $("setup-next").textContent = step === STEPS ? "Find my jobs" : "Next";
  $("setup-error").hidden = true;
  const first = document.querySelector(`#view-setup .step[data-step="${step}"] input`);
  if (first && first.type !== "radio") first.focus();
}

function setupError(text) {
  $("setup-error").textContent = text;
  $("setup-error").hidden = false;
}

$("setup-back").onclick = () => { if (step > 1) { step--; showStep(); } };
$("setup-next").onclick = async () => {
  if (step === 2 && !splitCities($("setup-cities").value).length && !$("setup-remote").checked) {
    return setupError("Add a city, or check “Include remote jobs”.");
  }
  if (step === 3 && $("setup-pay").value.trim() && !/^\$?[\d,.]+k?$/i.test($("setup-pay").value.trim())) {
    return setupError("Type a number like 150k, or 0 for no minimum.");
  }
  if (step === 4 && stillChecking("setup")) {
    return setupError("Still looking up companies. One moment…");
  }
  if (step < STEPS) { step++; return showStep(); }
  if (chosen("setup-tracker") === "notion" && !state.connected.notion) {
    return setupError("Connect Notion first, or pick the spreadsheet. You can switch any time.");
  }
  $("setup-next").disabled = true;
  try {
    state = await api("/api/settings", {
      level: chosen("setup-level"),
      cities: splitCities($("setup-cities").value),
      remote: $("setup-remote").checked,
      min_salary: $("setup-pay").value.trim() || "0",
      companies: companiesForSave("setup"),
      tracker: chosen("setup-tracker"),
    });
    renderHome();
    show("home");
    findJobs();
  } catch (e) {
    setupError(e.message);
  }
  $("setup-next").disabled = false;
};
document.querySelectorAll("#view-setup input:not([type=radio])").forEach((el) =>
  el.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !el.closest(".company-add")) $("setup-next").click();
  }));

// ── Home ───────────────────────────────────────────────────────────

function whenText(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const days = Math.floor((new Date().setHours(0, 0, 0, 0) - new Date(d).setHours(0, 0, 0, 0)) / 864e5);
  if (days === 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 7) return d.toLocaleDateString(undefined, { weekday: "long" });
  return d.toLocaleDateString(undefined, { month: "long", day: "numeric" });
}

const localDate = (ymd) => {
  const [y, m, d] = String(ymd).split("-").map(Number);
  return y && m && d ? new Date(y, m - 1, d) : null;
};
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

// "Posted 3 days ago"; old means past two weeks, shown fainter.
function postedAgo(ymd) {
  const d = localDate(ymd);
  if (!d) return null;
  const days = Math.max(0, Math.round((new Date().setHours(0, 0, 0, 0) - d) / 864e5));
  const text = days === 0 ? "Posted today" : days === 1 ? "Posted yesterday"
    : days < 14 ? `Posted ${days} days ago` : `Posted ${Math.floor(days / 7)} weeks ago`;
  return { text, old: days > 14 };
}

function nextCheckText(iso) {
  const d = new Date(iso);
  const day = d.toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" });
  const time = d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  return `Next check: ${day} at ${time}. If your Mac is asleep then, it checks when it wakes.`;
}

function jobCard(job) {
  const unlisted = !job.salary || job.salary.startsWith("unlisted");
  const age = postedAgo(job.posted_date);
  const a = el("a", "",
    el("span", "head", el("span", "company", job.company),
      age && el("span", "age" + (age.old ? " old" : ""), age.text)),
    el("span", "title", job.title, " ", icon("arrowUpRight", 16)),
    el("span", "meta", job.location, job.location ? " · " : "",
      unlisted ? el("span", "tag warn", icon("circleAlert", 12), "Pay not listed") : job.salary));
  a.href = /^https?:/.test(job.url) ? job.url : "#";
  a.target = "_blank";
  a.rel = "noopener";
  const li = el("li", "", a);
  const why = job.why || [];
  if (why.length || job.draft) {
    li.append(el("div", "why",
      why.length ? el("span", "", el("span", "key", "Matched"), why.join(" · ")) : el("span"),
      job.draft && el("span", "tag", icon("fileText", 12), "Draft ready")));
  }
  return li;
}

const SUGGEST = {
  bad_location: ["Most jobs were skipped because of their location.", "Add cities or remote jobs", "sec-location"],
  no_seniority: ["Most jobs were skipped because of their level.", "Change the level", "sec-level"],
  salary_too_low: ["Most jobs were skipped because their pay is below your minimum.", "Change the minimum pay", "sec-pay"],
};

// When nothing matched, point at the setting that skipped the most jobs.
function suggestion(last) {
  if (!last || last.state !== "done" || last.matches) return null;
  const top = Object.entries(last.skipped || {}).filter(([k]) => SUGGEST[k]).sort((a, b) => b[1] - a[1])[0];
  if (!top) return null;
  const [text, button, section] = SUGGEST[top[0]];
  return [`${text} (${top[1]} of ${last.scanned})`, button, section];
}

const shortDate = (ymd) => localDate(ymd).toLocaleDateString(undefined, { month: "short", day: "numeric" });
const longDate = (ymd) => localDate(ymd).toLocaleDateString(undefined, { month: "long", day: "numeric" });

// The week shown: the one clicked, else the latest week that was checked.
function selectedWeek(weeks) {
  const picked = weeks.find((w) => w.start === pickedWeek);
  if (picked) return picked;
  return [...weeks].reverse().find((w) => w.checked) || weeks[weeks.length - 1] || null;
}

// The strip: one tile per week, then the next check. Hidden until
// there are two checked weeks to compare.
function renderWeeks(weeks, shown, running) {
  const nav = $("weeks");
  nav.hidden = weeks.filter((w) => w.checked).length < 2;
  if (nav.hidden) return nav.replaceChildren();
  const tiles = weeks.map((w) => {
    const n = w.jobs.length;
    const checking = running && w.this_week;
    const count = checking ? [icon("rotateCw", 12), "Checking…"]
      : !w.checked ? [w.this_week ? "Not checked yet" : "Not checked"]
      : [w.this_week || !n ? `${n} new` : plural(n, "job")];
    const tile = el("button", "week" + (w.checked ? "" : " unchecked") + (w.checked && !n ? " empty" : "")
        + (w === shown ? " selected" : ""),
      el("span", "date", shortDate(w.start), w.problem && el("span", "alert", icon("circleAlert", 12))),
      el("span", "count", ...count));
    if (checking) tile.querySelector(".icon").classList.add("spin");
    if (w === shown) tile.setAttribute("aria-current", "true");
    if (w.problem) tile.title = "Some sites didn’t respond that week";
    tile.onclick = () => { pickedWeek = w.start; renderHome(); };
    return tile;
  });
  if (state.can_schedule) {
    if (state.schedule_on && state.next_check) {
      const next = new Date(state.next_check);
      tiles.push(el("div", "week next",
        el("span", "date", icon("calendarClock", 13), next.toLocaleDateString(undefined, { month: "short", day: "numeric" })),
        el("span", "count", "Next check")));
    } else {
      const on = el("button", "link", "Turn on");
      on.onclick = () => setSchedule(true);
      tiles.push(el("div", "week next", el("span", "date", "Not scheduled"), on));
    }
  }
  nav.replaceChildren(...tiles);
}

function renderHome() {
  const notion = state.settings.tracker === "notion" && state.connected.notion;
  const where = notion ? "Notion" : "your spreadsheet";
  const weeks = state.weeks || [];
  const week = selectedWeek(weeks);
  const latest = [...weeks].reverse().find((w) => w.checked);
  const last = week ? week.last : null;
  const run = state.run;
  const running = !!run && run.state === "running";
  // A search that stopped leads the page, but only on the latest week.
  const isLatest = !latest || week === latest;
  const problem = !isLatest ? null
    : run && run.state === "error" ? run : last && last.state === "error" ? last : null;

  renderWeeks(weeks, week, running);
  $("open-tracker").textContent = notion ? "Open Notion" : "Open my spreadsheet";
  $("close-sheet").hidden = notion;
  const title = $("home-title"), sub = $("home-sub");
  $("home-problem").hidden = !problem;
  $("find-big").hidden = true;

  if (problem && !running) {
    title.textContent = "The last check didn’t finish";
    sub.textContent = week && week.jobs.length
      ? `Jobs it found before that are below. Last checked ${whenText(state.last_checked)}.` : "";
    $("home-problem").replaceChildren(icon("circleAlert", 16), problem.message || "Something went wrong.");
    $("find-big").textContent = "Try again";
    $("find-big").hidden = false;
  } else if (!week) {
    title.textContent = "Let’s find your first jobs";
    sub.textContent = state.last_run && state.last_run.finished_at
      ? `Job Finder now keeps each week’s jobs on this page. Your earlier ones are in ${where}.`
      : `Job Finder checks Indeed and the careers pages of your companies, then adds the jobs that match to ${where}.`;
    $("find-big").textContent = "Find my first jobs";
    $("find-big").hidden = running;
  } else if (!week.checked) {
    title.textContent = week.this_week ? "Not checked yet this week" : `Not checked the week of ${longDate(week.start)}`;
    sub.textContent = week.this_week
      ? `${state.last_checked ? `Last checked ${whenText(state.last_checked)}. ` : ""}Click Find new jobs to look now.`
      : "Your Mac was off or asleep all that week, or Monday checks were turned off.";
  } else {
    const n = week.jobs.length;
    const when = `${week.this_week ? "Last checked" : "Checked"} ${whenText(last.finished_at)}.`;
    if (n) {
      title.textContent = `${plural(n, "new job")} ${week.this_week ? "this week" : `from the week of ${longDate(week.start)}`}`;
      sub.textContent = `${when} ${n === 1 ? "It matches" : "Each one matches"} your level, location and pay. Open the ones that look good, then mark what you decide in ${where}.`;
    } else {
      title.textContent = week.this_week ? "Nothing new this week" : `Nothing new the week of ${longDate(week.start)}`;
      sub.textContent = last.matches && last.already >= last.matches
        ? `${when} You’re up to date: the ${plural(last.matches, "job")} that matched ${last.matches === 1 ? "is" : "are"} already in ${where}.`
        : `${when} Job Finder looked at ${plural(last.scanned || 0, "listing")} and none matched your settings.`;
    }
  }

  // Problems that didn't stop the search: one quiet line each.
  const notes = [];
  if (last && last.source_problem) notes.push(el("p", "note", icon("circleAlert", 14), last.source_problem));
  if (last && last.draft_problem && isLatest) {
    const go = el("button", "link", "Open drafts settings");
    go.onclick = () => openSettings("sec-drafts");
    notes.push(el("p", "note", icon("circleAlert", 14), last.draft_problem, " ", go));
  }
  $("home-notes").replaceChildren(...notes);

  const tip = problem || !isLatest ? null : suggestion(last);
  $("run-suggest").hidden = !tip;
  if (tip) {
    $("suggest-text").textContent = tip[0];
    $("suggest-go").textContent = tip[1];
    $("suggest-go").onclick = () => openSettings(tip[2]);
  }

  $("jobs").replaceChildren(...(week ? week.jobs.map(jobCard) : []));

  $("run-progress").hidden = !running;
  if (running) $("run-step").textContent = run.step || "Starting…";
  $("find").disabled = $("find-big").disabled = running;
  $("find-label").textContent = running ? "Looking…" : "Find new jobs";
  // The big button, when it shows, is the one way to search: no twin in the top bar.
  if (!$("view-home").hidden) $("find").hidden = !$("find-big").hidden;

  $("schedule").checked = state.schedule_on;
  $("schedule").closest("label").hidden = !state.can_schedule;
  $("schedule-note").textContent = state.schedule_on && state.next_check
    ? nextCheckText(state.next_check)
    : "Your Mac looks for new jobs on its own and lets you know what it found. If it’s asleep then, it checks when it wakes.";
}

async function setSchedule(on) {
  try {
    Object.assign(state, await api("/api/schedule", { on }));
  } catch (err) { banner(err.message); }
  renderHome();
}

async function findJobs() {
  banner("");
  pickedWeek = null;  // show the new results
  try {
    state.run = await api("/api/run");
    renderHome();
    poll();
  } catch (e) {
    banner(e.message);
  }
}

function poll() {
  clearTimeout(polling);
  polling = setTimeout(async () => {
    try {
      const r = await api("/api/run/status");
      Object.assign(state, r);
      renderHome();
      if (r.run && r.run.state === "running") poll();
    } catch (e) {
      banner(e.message);
    }
  }, 1000);
}

$("find").onclick = findJobs;
$("find-big").onclick = findJobs;
$("open-tracker").onclick = async () => {
  try {
    const r = await api("/api/open-tracker");
    banner(r.ok ? "" : r.message);
  } catch (e) { banner(e.message); }
};
$("schedule").onchange = (e) => setSchedule(e.target.checked);

// ── Settings ───────────────────────────────────────────────────────

function openSettings(section) {
  const s = state.settings;
  choiceList($("set-level"), "set-level", levelOptions(), s.level);
  $("set-role").value = s.role;
  $("set-cities").value = s.cities.map(titleCase).join(", ");
  $("set-remote").checked = s.remote;
  $("set-pay").value = money(s.min_salary);
  companies.settings = s.companies.map((c) => ({ ...c, status: "found" }));
  renderCompanies("settings");
  choiceList($("set-tracker"), "set-tracker", TRACKERS, s.tracker);
  wireTrackerChoice($("set-tracker"), document.querySelector('.notion-connect[data-for="settings"]'));
  $("notes").value = state.notes;
  setConnected($("anthropic-status"), state.connected.anthropic);
  setConnected($("adzuna-status"), state.connected.adzuna);
  for (const id of ["settings-saved", "settings-error", "drafts-saved", "adzuna-saved"]) $(id).hidden = true;
  show("settings");
  if (section) $(section).scrollIntoView({ behavior: "smooth" });
}

function flash(id) {
  $(id).hidden = false;
  setTimeout(() => { $(id).hidden = true; }, 2500);
}

$("settings-save").onclick = async () => {
  $("settings-error").hidden = true;
  const problem = stillChecking("settings")
    ? "Still looking up companies. One moment…"
    : chosen("set-tracker") === "notion" && !state.connected.notion
      ? "Connect Notion first, or pick the spreadsheet. You can switch any time." : "";
  if (problem) {
    $("settings-error").textContent = problem;
    $("settings-error").hidden = false;
    return;
  }
  try {
    state = await api("/api/settings", {
      level: chosen("set-level"),
      role: $("set-role").value,
      cities: splitCities($("set-cities").value),
      remote: $("set-remote").checked,
      min_salary: $("set-pay").value.trim() || "0",
      companies: companiesForSave("settings"),
      tracker: chosen("set-tracker"),
    });
    $("set-role").value = state.settings.role;
    flash("settings-saved");
  } catch (e) {
    $("settings-error").textContent = e.message;
    $("settings-error").hidden = false;
  }
};

$("drafts-save").onclick = async () => {
  try {
    await api("/api/notes", { text: $("notes").value });
    state.notes = $("notes").value;
    const key = $("anthropic-key").value;
    if (key) {
      const r = await api("/api/keys", { anthropic: key });
      if (r.problems.length) return banner(r.problems[0]);
      state.connected = r.connected;
      $("anthropic-key").value = "";
      setConnected($("anthropic-status"), true);
    }
    banner("");
    flash("drafts-saved");
  } catch (e) { banner(e.message); }
};

$("adzuna-save").onclick = async () => {
  try {
    const r = await api("/api/keys", { adzuna_id: $("adzuna-id").value, adzuna_key: $("adzuna-key").value });
    if (r.problems.length) return banner(r.problems[0]);
    state.connected = r.connected;
    $("adzuna-id").value = $("adzuna-key").value = "";
    setConnected($("adzuna-status"), state.connected.adzuna);
    banner("");
    flash("adzuna-saved");
  } catch (e) { banner(e.message); }
};

$("to-settings").onclick = () => openSettings();
$("to-home").onclick = () => { banner(""); renderHome(); show("home"); };

// ── Start ──────────────────────────────────────────────────────────

(async () => {
  try {
    state = await api("/api/state");
  } catch (e) {
    banner(token ? e.message : "Click Job Finder in your Dock to open it.");
    return;
  }
  if (!state.set_up) return startSetup();
  renderHome();
  show("home");
  if (state.run && state.run.state === "running") poll();
})();
