// Design Job Finder page. Talks only to the small server on this Mac (app_server.py).
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
let pickedWeek = null;     // a week picked from the menu (its start date)
let page = "jobs";         // jobs, companies or settings

async function api(path, body = {}) {
  let res;
  try {
    res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Token": token || "" },
      body: JSON.stringify(body),
    });
  } catch (_) {
    throw new Error("Design Job Finder was closed. Click Design Job Finder in your Dock to open it again.");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "Something went wrong.");
  return data;
}

// A message that applies anywhere, shown at the bottom of the window.
function banner(text) {
  $("banner-text").textContent = text || "";
  $("banner").hidden = !text;
}
$("banner-close").onclick = () => banner("");

// Icons are Lucide (lucide.dev), drawn inline so the app works offline.
const ICONS = {
  arrowDown: '<path d="M12 5v14"/><path d="m19 12-7 7-7-7"/>',
  arrowUp: '<path d="m5 12 7-7 7 7"/><path d="M12 19V5"/>',
  arrowUpRight: '<path d="M7 7h10v10"/><path d="M7 17 17 7"/>',
  arrowUpDown: '<path d="m21 16-4 4-4-4"/><path d="M17 20V4"/><path d="m3 8 4-4 4 4"/><path d="M7 4v16"/>',
  calendar: '<path d="M8 2v4"/><path d="M16 2v4"/><rect width="18" height="18" x="3" y="4" rx="2"/><path d="M3 10h18"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  chevronDown: '<path d="m6 9 6 6 6-6"/>',
  circleAlert: '<circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/>',
  circleCheck: '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
  fileText: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>',
  loader: '<path d="M21 12a9 9 0 1 1-6.219-8.56"/>',
  rotateCw: '<path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/>',
  x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
};
function icon(name, cls = "") {
  const t = document.createElement("template");
  t.innerHTML = `<svg class="icon ${cls}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name]}</svg>`;
  return t.content.firstChild;
}
function el(tag, className, ...children) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.append(...children.filter((c) => c != null && c !== false && c !== ""));
  return node;
}
function button(className, onclick, ...children) {
  const b = el("button", className, ...children);
  b.type = "button";
  b.onclick = onclick;
  return b;
}
// A notice above a list, with an X to hide it. It stays hidden until its
// message or the search behind it changes (`key` covers both).
const DISMISSED_KEY = "dismissedNotices";
let dismissed = new Set();
try { dismissed = new Set(JSON.parse(localStorage.getItem(DISMISSED_KEY) || "[]")); } catch (e) {}
function notice(className, key, ...children) {
  if (dismissed.has(key)) return null;
  const node = el("div", className, icon("circleAlert", "sm"), el("div", "notice-body", ...children));
  node.append(button("btn btn-icon notice-close", () => {
    dismissed.add(key);
    try { localStorage.setItem(DISMISSED_KEY, JSON.stringify([...dismissed].slice(-50))); } catch (e) {}
    node.remove();
  }, icon("x", "sm")));
  node.lastChild.setAttribute("aria-label", "Dismiss");
  return node;
}
function setConnected(node, on) {
  node.replaceChildren(...(on ? [el("span", "dot ok"), "Connected"] : []));
}

// ── Pages ──────────────────────────────────────────────────────────

function show(view) {
  $("view-setup").hidden = view !== "setup";
  $("app").hidden = view === "setup";
  if (view !== "setup") {
    page = view;
    for (const p of ["jobs", "companies", "settings"]) $("view-" + p).hidden = p !== view;
    document.querySelectorAll(".nav [data-page]").forEach((b) => {
      if (b.dataset.page === view) b.setAttribute("aria-current", "page");
      else b.removeAttribute("aria-current");
    });
  }
  closeMenu();
}

document.querySelectorAll(".nav [data-page]").forEach((b) => {
  b.onclick = () => {
    const to = b.dataset.page;
    if (to === page) return;
    if (page === "settings" && settingsDirty) return saveStatus("Save or discard your changes first.", "bad");
    banner("");
    if (to === "settings") return openSettings();
    if (to === "companies") return openCompanies();
    renderJobs();
    show("jobs");
  };
});

// The sidebar: counts, the tracker button and the Monday check.
function renderSide() {
  const notion = state.settings.tracker === "notion" && state.connected.notion;
  $("open-tracker-label").textContent = notion ? "Open Notion" : "Open spreadsheet";
  $("close-sheet").hidden = notion;

  const weeks = state.weeks || [];
  const now = weeks.find((w) => w.this_week && w.checked);
  $("nav-jobs").hidden = !(now && now.jobs.length);
  if (now) $("nav-jobs").textContent = now.jobs.length;
  const saved = state.settings.companies.length;
  $("nav-companies").hidden = !saved;
  $("nav-companies").textContent = saved;

  $("schedule-row").hidden = !state.can_schedule;
  $("schedule").checked = state.schedule_on;
  $("schedule-note").textContent = state.schedule_on && state.next_check
    ? `Next: ${nextCheckShort(state.next_check)}` : "Off";
  $("schedule-row").title = "Your Mac looks for new jobs on its own and lets you know what it found. If it’s asleep then, it checks when it wakes.";
}

// ── Menus (the week picker and sorting) ────────────────────────────

let openMenu = null;   // { btn, menu }

function closeMenu() {
  if (!openMenu) return;
  openMenu.menu.remove();
  openMenu.btn.setAttribute("aria-expanded", "false");
  openMenu = null;
}
function toggleMenu(btn, build) {
  const same = openMenu && openMenu.btn === btn;
  closeMenu();
  if (same) return;
  const menu = el("div", "menu", ...build());
  menu.setAttribute("role", "menu");
  btn.after(menu);
  btn.setAttribute("aria-expanded", "true");
  openMenu = { btn, menu };
  const first = menu.querySelector('[aria-checked="true"]') || menu.querySelector('[role^="menuitem"]');
  if (first) first.focus();
}
function menuItem(checked, onclick, ...children) {
  const b = button("", onclick, el("span", "tick", checked && icon("check", "sm")), ...children);
  b.setAttribute("role", "menuitemradio");
  b.setAttribute("aria-checked", String(checked));
  return b;
}
document.addEventListener("click", (e) => {
  if (openMenu && !openMenu.menu.contains(e.target) && !openMenu.btn.contains(e.target)) closeMenu();
});
document.addEventListener("keydown", (e) => {
  if (!openMenu) return;
  if (e.key === "Escape") {
    const b = openMenu.btn;
    closeMenu();
    b.focus();
  } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    const items = [...openMenu.menu.querySelectorAll('[role^="menuitem"]')];
    const i = items.indexOf(document.activeElement);
    const next = items[(i + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length];
    if (next) next.focus();
  }
});

// ── Small builders ─────────────────────────────────────────────────

function choiceList(container, name, options, selected) {
  container.replaceChildren(...options.map(([value, title, sub]) => {
    const input = el("input");
    input.type = "radio";
    input.name = name;
    input.value = value;
    input.checked = String(value) === String(selected);
    return el("label", "option", input, el("span", "radio"),
      el("span", "", el("b", "", title), sub && el("span", "sub", sub)));
  }));
}
const chosen = (name) => (document.querySelector(`input[name="${name}"]:checked`) || {}).value;

const fieldOptions = () => labelOptions(state.fields);
const levelOptions = () => labelOptions(state.levels);
function labelOptions(labels) {
  return labels.map((label, i) => {
    const [title, rest] = label.split(" (");
    return [i + 1, title, rest ? rest.replace(/\)$/, "") : ""];
  });
}
const TRACKERS = [
  ["spreadsheet", "A spreadsheet", "Opens in Excel or Google Sheets. Nothing to set up."],
  ["notion", "Notion", "Needs a free Notion account and about 3 minutes."],
];

const splitCities = (text) => text.split(",").map((s) => s.trim()).filter(Boolean);
const titleCase = (s) => s.replace(/\b\w/g, (c) => c.toUpperCase());
const money = (n) => (n ? `${Math.round(n / 1000)}k` : "0");
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

// ── Companies (setup's list and the Companies page) ────────────────

const BOARDS = { greenhouse_companies: "Greenhouse", lever_companies: "Lever", ashby_companies: "Ashby" };
const companies = { setup: [], companies: [] };   // [{key, slug, name, status, jobs}]
const companyName = (c) => c.name || titleCase(String(c.slug).replace(/[-_]+/g, " "));
const fromSettings = () => state.settings.companies.map((c) => ({ ...c, status: "found" }));
const companiesForSave = (where) =>
  companies[where].filter((c) => c.key && c.slug).map(({ key, slug }) => ({ key, slug }));
const stillChecking = (where) => companies[where].some((c) => c.status === "checking");

const STATUS = {
  found: () => el("span", "status", el("span", "dot ok"), "Found"),
  checking: () => el("span", "status", icon("loader", "sm spin"), "Looking up…"),
  missing: () => el("span", "status", el("span", "dot bad"), "Not found"),
  error: () => el("span", "status", el("span", "dot warn"), "Couldn’t look up"),
};
// The job sites every check searches besides company careers pages,
// e.g. "Indeed and Adzuna", or "" when there are none.
function jobSites() {
  const names = [...(state.settings.job_sites || []), ...(state.connected.adzuna ? ["Adzuna"] : [])];
  return names.length > 1 ? `${names.slice(0, -1).join(", ")} and ${names.at(-1)}` : names.join("");
}
const HELP = {
  missing: () => "“Not found” means Design Job Finder can’t read that company’s careers page. Try another spelling, like the one in their careers page address, or remove it."
    + (jobSites() ? ` ${jobSites()} often list${jobSites().includes(" and ") ? "" : "s"} their jobs anyway.` : ""),
  error: () => "“Couldn’t look up” means the lookup didn’t finish. Click Retry to try again.",
};
// A company someone added that was already on the list, under any spelling.
const already = { setup: "", companies: "" };

function removeCompany(where, c) {
  companies[where].splice(companies[where].indexOf(c), 1);
  renderCompanies(where);
  if (where === "companies" && c.key) saveCompanies();
}

function renderCompanies(where) {
  const list = companies[where];
  if (where === "setup") {
    $("setup-companies").replaceChildren(...list.map((c) => {
      const note = { checking: "looking up…", missing: "not found", error: "couldn’t look up" }[c.status];
      const dot = c.status === "checking" ? icon("loader", "xs spin")
        : el("span", "dot " + ({ found: "ok", missing: "bad", error: "warn" }[c.status] || "ok"));
      const x = button("", () => removeCompany(where, c), icon("x", "xs"));
      x.setAttribute("aria-label", `Remove ${companyName(c)}`);
      let retry = null;
      if (c.status === "error") {
        retry = button("", () => lookUp(where, c), icon("rotateCw", "xs"));
        retry.setAttribute("aria-label", `Look up ${companyName(c)} again`);
        retry.title = "Retry";
      }
      return el("li", "chip", dot, companyName(c), note && el("span", "faint", note), retry, x);
    }));
    const help = [already.setup, ...["missing", "error"].filter((s) => list.some((c) => c.status === s)).map((s) => HELP[s]())]
      .filter(Boolean).join(" ");
    $("setup-co-help").textContent = help;
    $("setup-co-help").hidden = !help;
    return;
  }

  $("co-count").textContent = list.length;
  $("co-count").hidden = !list.length;
  const found = list.filter((c) => c.status === "found").length;
  $("co-title").textContent = !list.length ? "No companies yet"
    : found === list.length ? plural(list.length, "company") : `${found} of ${list.length} companies found`;
  $("co-wrap").hidden = !list.length;
  $("co-empty").hidden = !!list.length;
  const sites = jobSites();
  $("co-sub").textContent = sites ? `Each check includes these careers pages, along with ${sites}.`
    : "Each check includes these careers pages.";
  $("co-empty-text").textContent = "Add companies you’d love to work at, and each check will include their careers pages."
    + (sites ? ` Without any, Design Job Finder still searches ${sites}.` : "");
  $("companies").replaceChildren(...list.map((c) => {
    const x = button("btn btn-icon", () => removeCompany(where, c), icon("x", "sm"));
    x.setAttribute("aria-label", `Remove ${companyName(c)}`);
    return el("tr", "",
      el("td", "", el("span", "cell", el("span", "avatar", companyName(c)[0]), companyName(c))),
      el("td", "", el("span", "cell", (STATUS[c.status] || STATUS.found)(),
        c.status === "error" && button("btn btn-ghost", () => lookUp(where, c), "Retry"))),
      el("td", BOARDS[c.key] ? "soft" : "faint", BOARDS[c.key] || "—"),
      el("td", c.jobs ? "" : "faint", c.jobs != null ? String(c.jobs) : "—"),
      el("td", "shrink", x));
  }));
  $("co-notices").replaceChildren(...[
    already.companies && notice("notice", "co:already:" + already.companies, el("p", "", already.companies)),
    ...["missing", "error"]
      .filter((s) => list.some((c) => c.status === s))
      .map((s) => notice("notice", "co:" + s + ":" + list.filter((c) => c.status === s).map((c) => c.key || c.name).join(","),
        el("p", "", HELP[s]()))),
  ].filter(Boolean));
  renderSide();
}

async function addCompanies(where, text) {
  const entries = splitCities(text).map((name) => ({ name, status: "checking" }));
  already[where] = "";
  companies[where].push(...entries);
  renderCompanies(where);
  await Promise.all(entries.map((entry) => lookUp(where, entry, false)));
  if (where === "companies" && entries.some((e) => e.status === "found")) saveCompanies();
}

// Look a company up (again, after "Couldn't look up"), then show the result.
async function lookUp(where, entry, save = true) {
  entry.status = "checking";
  renderCompanies(where);
  try {
    const r = await api("/api/company", { name: entry.name });
    Object.assign(entry, r.status === "found"
      ? { status: "found", key: r.key, slug: r.slug, jobs: r.jobs }
      : { status: r.status });
  } catch (e) {
    entry.status = "error";
  }
  // Already on the list under another spelling: keep the first one and say so.
  const first = entry.key && companies[where].find((c) => c !== entry && c.key === entry.key && c.slug === entry.slug);
  if (first) {
    companies[where].splice(companies[where].indexOf(entry), 1);
    already[where] = `${companyName(first)} is already on your list.`;
  }
  renderCompanies(where);
  if (save && where === "companies" && entry.status === "found" && !first) saveCompanies();
}

document.querySelectorAll(".company-add").forEach((box) => {
  const where = box.dataset.for;
  const input = box.querySelector("input");
  const go = () => { if (input.value.trim()) { addCompanies(where, input.value); input.value = ""; } };
  box.querySelector("button").onclick = go;
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); go(); } });
});

// The Companies page saves as soon as a company is added or removed,
// keeping every other setting as it is.
async function saveCompanies() {
  const s = state.settings;
  try {
    Object.assign(state, await api("/api/settings", {
      field: s.field, level: s.level, role: s.role, cities: s.cities, remote: s.remote,
      min_salary: String(s.min_salary || 0), tracker: s.tracker,
      companies: companiesForSave("companies"),
    }));
    renderSide();
  } catch (e) {
    banner(e.message);
  }
}

function openCompanies() {
  // Keep companies that weren't found, so people can see what happened.
  const unsaved = companies.companies.filter((c) => !c.key);
  const known = new Map(companies.companies.filter((c) => c.key).map((c) => [c.key + c.slug, c]));
  companies.companies = [...fromSettings().map((c) => known.get(c.key + c.slug) || c), ...unsaved];
  renderCompanies("companies");
  show("companies");
}

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
      if (r.ok) msg.replaceChildren(icon("circleCheck", "sm"), "Connected. A “Job applications” database was added to that page.");
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
  choiceList($("setup-field"), "setup-field", fieldOptions(), s.field || 1);
  choiceList($("setup-level"), "setup-level", levelOptions(), s.level);
  $("setup-cities").value = s.cities.map(titleCase).join(", ");
  $("setup-remote").checked = s.remote;
  $("setup-pay").value = s.min_salary ? money(s.min_salary) : "";
  $("setup-companies-lede").textContent = jobSites()
    ? `Optional. Each check includes these companies’ careers pages. Design Job Finder also searches ${jobSites()}, so you’ll still find jobs if you skip this.`
    : "Each check includes these companies’ careers pages.";
  companies.setup = fromSettings();
  renderCompanies("setup");
  choiceList($("setup-tracker"), "setup-tracker", TRACKERS, s.tracker);
  wireTrackerChoice($("setup-tracker"), document.querySelector('.notion-connect[data-for="setup"]'));
  step = 1;
  showStep();
  show("setup");
}

function showStep() {
  document.querySelectorAll("#view-setup .step").forEach((node) => {
    node.hidden = Number(node.dataset.step) !== step;
  });
  document.querySelectorAll("#setup-segs i").forEach((seg, i) => seg.classList.toggle("on", i < step));
  $("step-count").textContent = `Step ${step} of ${STEPS}`;
  $("setup-back").style.visibility = step > 1 ? "visible" : "hidden";
  $("setup-next").textContent = step === STEPS ? "Find my first jobs" : "Next";
  $("setup-error").hidden = true;
  const first = document.querySelector(`#view-setup .step[data-step="${step}"] input`);
  if (first && first.type !== "radio" && first.type !== "checkbox") first.focus();
}

function setupError(text) {
  $("setup-error").textContent = text;
  $("setup-error").hidden = false;
}

$("setup-back").onclick = () => { if (step > 1) { step--; showStep(); } };
$("setup-next").onclick = async () => {
  if (step === 2 && !splitCities($("setup-cities").value).length && !$("setup-remote").checked) {
    return setupError("Add a city, or turn on “Include remote jobs”.");
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
      field: chosen("setup-field"),
      level: chosen("setup-level"),
      cities: splitCities($("setup-cities").value),
      remote: $("setup-remote").checked,
      min_salary: $("setup-pay").value.trim() || "0",
      companies: companiesForSave("setup"),
      tracker: chosen("setup-tracker"),
    });
    renderJobs();
    show("jobs");
    findJobs();
  } catch (e) {
    setupError(e.message);
  }
  $("setup-next").disabled = false;
};
document.querySelectorAll("#view-setup input:not([type=radio]):not([type=checkbox])").forEach((input) =>
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !input.closest(".company-add")) $("setup-next").click();
  }));

// ── Dates ──────────────────────────────────────────────────────────

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
const shortDate = (ymd) => localDate(ymd).toLocaleDateString(undefined, { month: "short", day: "numeric" });
const longDate = (ymd) => localDate(ymd).toLocaleDateString(undefined, { month: "long", day: "numeric" });

// "3 days ago"; old means past two weeks, shown fainter.
function postedAgo(ymd) {
  const d = localDate(ymd);
  if (!d) return null;
  const days = Math.max(0, Math.round((new Date().setHours(0, 0, 0, 0) - d) / 864e5));
  const text = days === 0 ? "Today" : days === 1 ? "Yesterday"
    : days < 14 ? `${days} days ago` : `${Math.floor(days / 7)} weeks ago`;
  return { text, old: days > 14 };
}

function nextCheckShort(iso) {
  const d = new Date(iso);
  return `${d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })}, ${
    d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}`;
}

// ── Jobs: sorting ──────────────────────────────────────────────────

// dir 1 is each column's natural order: newest, highest pay, A to Z.
const SORTS = {
  posted: ["Date posted", "Newest first", (j) => { const d = localDate(j.posted_date); return d ? -d.getTime() : null; }],
  pay: ["Pay", "Highest first", (j) => { const top = payTop(j.salary); return top == null ? null : -top; }],
  company: ["Company", "A to Z", (j) => (j.company || "").toLowerCase() || null],
};
let sort = { key: "posted", dir: 1 };
try {
  const saved = JSON.parse(localStorage.getItem("jf-sort"));
  if (saved && SORTS[saved.key] && Math.abs(saved.dir) === 1) sort = saved;
} catch (_) {}

function setSort(key, dir = 1) {
  sort = { key, dir };
  try { localStorage.setItem("jf-sort", JSON.stringify(sort)); } catch (_) {}
  closeMenu();
  renderJobs();
}

const unlisted = (salary) => !salary || salary.startsWith("unlisted");
// The top of a pay range: "$150,000 – $190,000" and "$150k-190k" give 190000.
function payTop(salary) {
  if (unlisted(salary)) return null;
  const nums = (salary.match(/\d[\d,.]*\s*k?/gi) || []).map((n) => {
    const v = parseFloat(n.replace(/[,\s]/g, ""));
    return /k$/i.test(n.trim()) ? v * 1000 : v;
  }).filter((v) => v >= 1000);
  return nums.length ? Math.max(...nums) : null;
}

// A match reason, in a word or two (the sentences come from sources.py _why).
function shortWhy(reason) {
  let m;
  if ((m = reason.match(/^(.+) is on your list$/))) return m[1];
  if ((m = reason.match(/^Pay reaches your (.+)$/))) return `Pay ${m[1]}+`;
  if (reason.startsWith("No level in the title")) return "Level from pay";
  if (reason === "Remote counts") return "Remote";
  if (reason.startsWith("Contract")) return "Contract";
  if (reason === "Check pay before applying") return "Check pay";
  return reason;
}

// "$170,016–$170,016" reads as one number, so show it once.
function payText(salary) {
  const parts = salary.split(/\s*[–—-]\s*/);
  return parts.length === 2 && parts[0] === parts[1] ? parts[0] : salary;
}

function sortedJobs(jobs) {
  const value = SORTS[sort.key][2];
  return [...jobs].sort((a, b) => {
    const x = value(a), y = value(b);
    if (x == null || y == null) return (x == null) - (y == null);  // missing always last
    return (x > y ? 1 : x < y ? -1 : 0) * sort.dir;
  });
}

document.querySelectorAll("table.jobs th[data-sort] button").forEach((b) => {
  const key = b.closest("th").dataset.sort;
  b.onclick = () => setSort(key, sort.key === key ? -sort.dir : 1);
});

$("sort-btn").onclick = () => toggleMenu($("sort-btn"), () => Object.entries(SORTS).map(([key, [label, order]]) =>
  menuItem(sort.key === key, () => setSort(key), el("span", "grow", label), el("span", "sub", order))));

// ── Jobs: the week picker ──────────────────────────────────────────

const weekLabel = (w) => (w.this_week ? "This week" : `Week of ${shortDate(w.start)}`);

// The week shown: the one picked, else the latest week that was checked.
function selectedWeek(weeks) {
  const picked = weeks.find((w) => w.start === pickedWeek);
  if (picked) return picked;
  return [...weeks].reverse().find((w) => w.checked) || weeks[weeks.length - 1] || null;
}

$("week-btn").onclick = () => toggleMenu($("week-btn"), () => {
  const weeks = state.weeks || [];
  const shown = selectedWeek(weeks);
  const items = [...weeks].reverse().map((w) => {
    const item = menuItem(w === shown, () => { pickedWeek = w.start; closeMenu(); renderJobs(); },
      el("span", "grow", weekLabel(w), w.this_week && el("span", "sub", " " + shortDate(w.start))),
      w.problem && el("span", "alert", icon("circleAlert", "sm")),
      w.checked ? el("span", "count", String(w.jobs.length)) : el("span", "sub", "Not checked"));
    if (w.problem) item.title = "Some sites didn’t respond that week";
    return item;
  });
  if (!state.can_schedule) return items;
  const foot = state.schedule_on && state.next_check
    ? el("div", "foot", icon("calendar", "sm"), `Next check ${nextCheckShort(state.next_check)}`)
    : el("div", "foot", icon("calendar", "sm"), "Monday checks are off",
        button("btn btn-secondary", () => { closeMenu(); setSchedule(true); }, "Turn on"));
  return [...items, el("hr"), foot];
});

// ── Jobs: the page ─────────────────────────────────────────────────

function jobRow(job) {
  const age = postedAgo(job.posted_date);
  const link = el("a", "role", el("span", "t", job.title), icon("arrowUpRight", "sm"));
  link.href = /^https?:/.test(job.url) ? job.url : "#";
  link.target = "_blank";
  link.rel = "noopener";
  link.title = job.title;
  const why = job.why || [];
  // Short chips; the full reasons show on hover.
  const whyCell = el("td", "", why.length
    ? el("span", "chips", ...why.map((w) => el("span", "chip", shortWhy(w)))) : el("span", "faint", "—"));
  if (why.length) whyCell.title = why.join("\n");
  const place = el("td", "soft trunc", el("span", "cell", el("span", "t", job.location || "—")));
  if (job.location) place.title = job.location;
  return el("tr", "",
    el("td", "trunc", el("span", "cell", el("span", "avatar", (job.company || "?")[0]), el("span", "t", job.company))),
    el("td", "trunc wide", el("span", "cell", link,
      job.draft && el("span", "chip", icon("fileText", "xs"), "Draft"))),
    place,
    el("td", "", unlisted(job.salary) ? el("span", "status faint", el("span", "dot warn"), "Not listed") : payText(job.salary)),
    el("td", age && age.old ? "old" : "soft", age ? age.text : "—"),
    whyCell);
}

const SUGGEST = {
  bad_location: ["were left out because of their location.", "Add cities or remote jobs", "sec-location"],
  no_seniority: ["were left out because of their level.", "Change level", "sec-level"],
  salary_too_low: ["were left out because their pay is below your minimum.", "Lower minimum pay", "sec-pay"],
};

// When nothing matched, point at the setting that skipped the most jobs.
function suggestion(last) {
  if (!last || last.state !== "done" || last.matches) return null;
  const top = Object.entries(last.skipped || {}).filter(([k]) => SUGGEST[k]).sort((a, b) => b[1] - a[1])[0];
  if (!top) return null;
  const [text, label, section] = SUGGEST[top[0]];
  return [`${top[1]} of ${last.scanned} ${text}`, label, section];
}

// The fix for a problem (a button to the right setting) and its details,
// which people can copy to ask someone for help. Keys are already hidden.
function problemActions(problem) {
  const actions = [];
  if (problem.fix && problem.fix.section) {
    actions.push(button("btn btn-secondary", () => openSettings(problem.fix.section), problem.fix.label || "Open Settings"));
  }
  if (problem.details) {
    const copy = button("btn btn-ghost", async () => {
      try {
        await navigator.clipboard.writeText(problem.details);
        copy.textContent = "Copied";
      } catch (_) {
        banner("Couldn’t copy the details. They’re also in the logs folder inside your job-search folder.");
      }
    }, "Copy details");
    actions.push(copy);
  }
  return actions;
}

function renderJobs() {
  renderSide();
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
  const problem = running || !isLatest ? null
    : run && run.state === "error" ? run : last && last.state === "error" ? last : null;
  const jobs = week ? week.jobs : [];

  // Toolbar
  $("week-wrap").hidden = !weeks.length;
  if (week) $("week-btn").replaceChildren(icon("calendar"), weekLabel(week), icon("chevronDown", "sm"));
  $("sort-wrap").hidden = !jobs.length;
  $("sort-btn").replaceChildren(icon("arrowUpDown"), el("span", "muted", "Sorted by"), SORTS[sort.key][0]);
  $("find").disabled = running;
  $("find").replaceChildren(icon("rotateCw", running ? "spin" : ""), running ? "Finding jobs…" : problem ? "Try again" : "Find new jobs");
  // A specific fix (like reconnecting Notion) comes before trying again,
  // and the first search has its own button in the middle of the page.
  $("find").hidden = !running && (!week || !!(problem && problem.fix));

  // Title and one line about the week
  let title, sub;
  const actions = [];
  if (problem) {
    title = "The last check didn’t finish";
    sub = jobs.length ? "Jobs it found before it stopped are below." : problem.message || "Something went wrong.";
  } else if (!week) {
    title = "Let’s find your first jobs";
    sub = state.last_run && state.last_run.finished_at
      ? `Design Job Finder now keeps each week’s jobs on this page. Your earlier ones are in ${where}.`
      : `Design Job Finder checks ${jobSites() ? jobSites() + " and " : ""}the careers pages of your companies, then adds the jobs that match to ${where}.`;
    if (!running) actions.push(button("btn btn-primary", findJobs, icon("rotateCw"), "Find my first jobs"));
  } else if (!week.checked) {
    title = week.this_week ? "Not checked yet this week" : `Not checked the week of ${longDate(week.start)}`;
    sub = week.this_week
      ? `${state.last_checked ? `Last checked ${whenText(state.last_checked)}. ` : ""}Click “Find new jobs” to check now.`
      : "Your Mac was off or asleep all that week, or Monday checks were turned off.";
  } else {
    const n = jobs.length;
    const when = `${week.this_week ? "Last checked" : "Checked"} ${whenText(last.finished_at)}.`;
    if (n) {
      title = `${plural(n, "new job")} ${week.this_week ? "this week" : `from the week of ${longDate(week.start)}`}`;
      sub = `${when} ${n === 1 ? "It matches" : "Each one matches"} your level, location and pay, and ${n === 1 ? "it’s" : "they’re"} in ${where} too.`;
    } else {
      title = week.this_week ? "Nothing new this week" : `Nothing new the week of ${longDate(week.start)}`;
      sub = last.matches && last.already >= last.matches
        ? `${when} You’re up to date: the ${plural(last.matches, "job")} that matched ${last.matches === 1 ? "is" : "are"} already in ${where}.`
        : `${when} Design Job Finder looked at ${plural(last.scanned || 0, "listing")} and none matched your search.`;
      const tip = isLatest ? suggestion(last) : null;
      if (tip) {
        sub += " " + tip[0];
        actions.push(button("btn btn-secondary", () => openSettings(tip[2]), tip[1]));
      }
    }
  }
  if (problem && !jobs.length) actions.push(...problemActions(problem));

  // With jobs: a summary line and the table. Without: an empty state.
  $("summary").hidden = !jobs.length;
  $("jobs-wrap").hidden = !jobs.length;
  $("jobs-empty").hidden = !!jobs.length;
  if (jobs.length) {
    $("summary-title").textContent = title;
    $("summary-sub").textContent = sub;
  } else {
    $("empty-title").textContent = title;
    $("empty-sub").textContent = sub;
    $("empty-actions").replaceChildren(...actions);
  }

  // Problems that didn't stop the search, and a stopped search above its jobs.
  const notices = [];
  const ran = (last && last.finished_at) || "";
  if (problem && jobs.length) {
    const acts = problemActions(problem);
    notices.push(notice("notice bad", "problem:" + ran + ":" + (problem.message || ""),
      el("p", "", problem.message || "Something went wrong."), acts.length && el("div", "actions", ...acts)));
  }
  if (last && last.source_problem) notices.push(notice("notice", "source:" + ran + ":" + last.source_problem, el("p", "", last.source_problem)));
  if (last && last.draft_problem && isLatest) {
    notices.push(notice("notice", "drafts:" + ran + ":" + last.draft_problem, el("p", "", last.draft_problem),
      el("div", "actions", button("btn btn-secondary", () => openSettings("sec-drafts"), "Open Drafts settings"))));
  }
  $("notices").replaceChildren(...notices.filter(Boolean));

  // The table
  document.querySelectorAll("table.jobs th[data-sort]").forEach((th) => {
    const on = th.dataset.sort === sort.key;
    const ascending = (sort.key === "company") === (sort.dir === 1);
    if (on) th.setAttribute("aria-sort", ascending ? "ascending" : "descending");
    else th.removeAttribute("aria-sort");
    th.querySelector(".arrow").replaceChildren(...(on ? [icon(sort.dir === 1 ? "arrowDown" : "arrowUp", "xs")] : []));
  });
  $("jobs").replaceChildren(...sortedJobs(jobs).map(jobRow));
  const drafts = jobs.filter((j) => j.draft).length;
  const noPay = jobs.filter((j) => unlisted(j.salary)).length;
  $("jobs-foot").replaceChildren(el("b", "", String(jobs.length)), ` ${jobs.length === 1 ? "job" : "jobs"}`,
    drafts ? ` · ${drafts} with ${drafts === 1 ? "a draft" : "drafts"}` : "",
    noPay ? ` · ${noPay} without listed pay` : "");

  // While searching
  $("run").hidden = !running;
  if (running) renderRun(run);
}

// While searching: every site, and what happened when it was checked.
const SITE_TEXT = { waiting: "Waiting", checking: "Checking…", failed: "Didn’t respond", skipped: "Skipped" };
function renderRun(run) {
  const sites = run.sites || [];
  const done = sites.filter((s) => !["waiting", "checking"].includes(s.state)).length;
  $("run-step").textContent = run.step || "Starting…";
  $("run-count").textContent = sites.length ? `${done} of ${sites.length}` : "";
  $("run-segs").hidden = !sites.length;
  $("run-segs").replaceChildren(...sites.map((s) => el("i", ["waiting", "checking"].includes(s.state) ? "" : "on")));
  $("run-sites").hidden = !sites.length;
  $("run-sites").replaceChildren(...sites.map((site) => {
    const mark = site.state === "done" ? icon("circleCheck", "sm")
      : site.state === "checking" ? icon("loader", "sm spin")
      : site.state === "failed" ? icon("circleAlert", "sm") : null;
    return el("li", site.state,
      el("span", "mark", mark),
      el("span", "name", site.name),
      el("span", "result", site.state === "done" ? plural(site.jobs, "job") : SITE_TEXT[site.state] || ""));
  }));
}

async function setSchedule(on) {
  try {
    Object.assign(state, await api("/api/schedule", { on }));
  } catch (err) { banner(err.message); }
  renderJobs();
}

async function findJobs() {
  banner("");
  pickedWeek = null;  // show the new results
  try {
    state.run = await api("/api/run");
    renderJobs();
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
      renderJobs();
      if (r.run && r.run.state === "running") poll();
    } catch (e) {
      banner(e.message);
    }
  }, 1000);
}

$("find").onclick = findJobs;
$("open-tracker").onclick = async () => {
  try {
    const r = await api("/api/open-tracker");
    banner(r.ok ? "" : r.message);
  } catch (e) { banner(e.message); }
};
$("schedule").onchange = (e) => setSchedule(e.target.checked);

// ── Settings ───────────────────────────────────────────────────────

// Two tabs, one Save for both. It says when something has changed, and
// leaving the page won't quietly drop unsaved changes.
let settingsDirty = false;

function setTab(name) {
  document.querySelectorAll("#view-settings [data-tab]").forEach((t) =>
    t.setAttribute("aria-selected", String(t.dataset.tab === name)));
  document.querySelectorAll("#view-settings [data-panel]").forEach((p) => { p.hidden = p.dataset.panel !== name; });
}
document.querySelectorAll("#view-settings [data-tab]").forEach((t) => { t.onclick = () => setTab(t.dataset.tab); });

function saveStatus(text, kind = "") {
  $("save-status").textContent = text;
  $("save-status").className = kind;
}

function markDirty() {
  if (!settingsDirty) saveStatus("Unsaved changes", "dirty");
  settingsDirty = true;
  $("save-all").disabled = false;
  $("discard").hidden = false;
}

function markClean(text = "No changes") {
  settingsDirty = false;
  saveStatus(text, text === "Saved" ? "ok" : "");
  $("save-all").disabled = true;
  $("discard").hidden = true;
}

function openSettings(section) {
  if (section === "sec-companies") return openCompanies();
  const s = state.settings;
  choiceList($("set-field"), "set-field", fieldOptions(), s.field);
  $("set-field-custom").hidden = Boolean(s.field);
  choiceList($("set-level"), "set-level", levelOptions(), s.level);
  $("set-role").value = s.role;
  $("set-cities").value = s.cities.map(titleCase).join(", ");
  $("set-remote").checked = s.remote;
  $("set-pay").value = money(s.min_salary);
  choiceList($("set-tracker"), "set-tracker", TRACKERS, s.tracker);
  wireTrackerChoice($("set-tracker"), document.querySelector('.notion-connect[data-for="settings"]'));
  $("notes").value = state.notes;
  $("anthropic-key").value = $("adzuna-id").value = $("adzuna-key").value = "";
  setConnected($("anthropic-status"), state.connected.anthropic);
  setConnected($("adzuna-status"), state.connected.adzuna);
  markClean();
  const target = section && $(section);
  setTab(target ? target.closest("[data-panel]").dataset.panel : "search");
  show("settings");
  if (target) target.scrollIntoView({ behavior: "smooth" });
  else $("view-settings").querySelector(".scroll").scrollTop = 0;
}

// Anything typed or picked counts, except the Notion panel (it has its
// own Connect button).
["input", "change"].forEach((type) => $("view-settings").addEventListener(type, (e) => {
  if (!e.target.closest(".notion-connect")) markDirty();
}));

// Checks that need no server, so nothing is half-saved.
function settingsProblem() {
  if (chosen("set-tracker") === "notion" && !state.connected.notion)
    return "Connect Notion first, or pick the spreadsheet. You can switch any time.";
  const key = $("anthropic-key").value.trim();
  if (key && !key.startsWith("sk-ant-")) return "That doesn’t look like an Anthropic key. They start with sk-ant-.";
  if (!$("adzuna-id").value.trim() !== !$("adzuna-key").value.trim())
    return "Adzuna needs both the App ID and the App Key.";
  return "";
}

$("save-all").onclick = async () => {
  const problem = settingsProblem();
  if (problem) return saveStatus(problem, "bad");
  $("save-all").disabled = true;
  saveStatus("Saving…");
  try {
    const saved = await api("/api/settings", {
      field: chosen("set-field"),
      level: chosen("set-level"),
      role: $("set-role").value,
      cities: splitCities($("set-cities").value),
      remote: $("set-remote").checked,
      min_salary: $("set-pay").value.trim() || "0",
      companies: state.settings.companies,
      tracker: chosen("set-tracker"),
    });
    Object.assign(state, saved);
    $("set-role").value = state.settings.role;
    if ($("notes").value !== state.notes) {
      await api("/api/notes", { text: $("notes").value });
      state.notes = $("notes").value;
    }
    const keys = { anthropic: $("anthropic-key").value, adzuna_id: $("adzuna-id").value,
                   adzuna_key: $("adzuna-key").value };
    if (Object.values(keys).some((v) => v.trim())) {
      const r = await api("/api/keys", keys);
      if (r.problems.length) throw new Error(r.problems[0]);
      state.connected = r.connected;
      $("anthropic-key").value = $("adzuna-id").value = $("adzuna-key").value = "";
      setConnected($("anthropic-status"), state.connected.anthropic);
      setConnected($("adzuna-status"), state.connected.adzuna);
    }
    markClean("Saved");
    renderSide();
  } catch (e) {
    saveStatus(e.message, "bad");
    $("save-all").disabled = false;
  }
};

$("discard").onclick = () => openSettings();

// ── Start ──────────────────────────────────────────────────────────

(async () => {
  try {
    state = await api("/api/state");
  } catch (e) {
    banner(token ? e.message : "Click Design Job Finder in your Dock to open it.");
    return;
  }
  if (!state.set_up) return startSetup();
  renderJobs();
  show("jobs");
  if (state.run && state.run.state === "running") poll();
})();
