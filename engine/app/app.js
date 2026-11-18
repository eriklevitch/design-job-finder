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
  $("to-home").hidden = view !== "settings";
  window.scrollTo(0, 0);
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
    const note = { checking: "checking…", missing: "not found", error: "couldn’t check" }[c.status]
      || (c.jobs != null ? `✓ ${c.jobs} open job${c.jobs === 1 ? "" : "s"}` : "");
    if (note) {
      const n = document.createElement("span");
      n.className = "note";
      n.textContent = note;
      li.append(n);
    }
    const x = document.createElement("button");
    x.textContent = "×";
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
      msg.textContent = r.ok ? "✓ Connected. A “Job applications” database was added to that page." : r.message;
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

function renderHome() {
  const notion = state.settings.tracker === "notion" && state.connected.notion;
  $("open-tracker").textContent = notion ? "Open Notion" : "Open my spreadsheet";
  $("close-sheet").hidden = notion;
  const last = state.last_run;
  $("last-run").textContent = last && last.finished_at
    ? `Last checked ${whenText(last.finished_at)} · ${last.added} new job${last.added === 1 ? "" : "s"}`
    : `Find matching jobs and add them to ${notion ? "Notion" : "your spreadsheet"}.`;
  $("schedule").checked = state.schedule_on;
  $("schedule").closest("label").hidden = !state.can_schedule;
  if (state.run) renderRun(state.run);
}

const SUGGEST = {
  bad_location: ["Most jobs were skipped because of their location.", "Add cities or remote jobs", "sec-location"],
  no_seniority: ["Most jobs were skipped because of their level.", "Change the level", "sec-level"],
  salary_too_low: ["Most jobs were skipped because their pay is below your minimum.", "Change the minimum pay", "sec-pay"],
};

function renderRun(run) {
  $("run").hidden = false;
  const running = run.state === "running";
  $("run-progress").hidden = !running;
  $("run-result").hidden = running;
  $("find").disabled = running;
  $("find").textContent = running ? "Looking for jobs…" : "Find new jobs";
  if (running) { $("run-step").textContent = run.step || "Starting…"; return; }

  $("run-message").textContent = run.message || "";
  $("run-message").className = "result" + (run.state === "error" ? " bad" : "");

  // When little matched, point at the setting that skipped the most jobs.
  const skipped = Object.entries(run.skipped || {}).filter(([k]) => SUGGEST[k]);
  skipped.sort((a, b) => b[1] - a[1]);
  const top = run.state === "done" && !run.matches && skipped[0];
  let suggestion = null;
  if (top) {
    const [text, button, section] = SUGGEST[top[0]];
    suggestion = [`${text} (${top[1]} of ${run.scanned})`, button, section];
  } else if (run.draft_problem) {
    suggestion = [run.draft_problem, "Open drafts settings", "sec-drafts"];
  }
  $("run-suggest").hidden = !suggestion;
  if (suggestion) {
    $("suggest-text").textContent = suggestion[0];
    $("suggest-go").textContent = suggestion[1];
    $("suggest-go").onclick = () => openSettings(suggestion[2]);
  }

  const ul = $("run-jobs");
  ul.innerHTML = "";
  (run.added || []).forEach((job) => {
    const li = document.createElement("li");
    const a = document.createElement("a");
    a.href = /^https?:/.test(job.url) ? job.url : "#";
    a.target = "_blank";
    a.rel = "noopener";
    const part = (cls, text) => {
      const el = document.createElement("span");
      el.className = cls;
      el.textContent = text;
      return el;
    };
    a.append(
      part("company", job.company),
      part("title", job.title),
      part("meta", [job.location, job.salary && !job.salary.startsWith("unlisted") ? job.salary : ""]
        .filter(Boolean).join(" · ")),
    );
    li.append(a);
    ul.append(li);
  });
}

async function findJobs() {
  banner("");
  try {
    renderRun(await api("/api/run"));
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
      if (r.run) renderRun(r.run);
      if (r.run && r.run.state === "running") return poll();
      state.last_run = r.last_run;
      renderHome();
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
$("schedule").onchange = async (e) => {
  try {
    state.schedule_on = (await api("/api/schedule", { on: e.target.checked })).schedule_on;
  } catch (err) { banner(err.message); }
  e.target.checked = state.schedule_on;
};

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
  $("anthropic-status").textContent = state.connected.anthropic ? "✓ Connected" : "";
  $("adzuna-status").textContent = state.connected.adzuna ? "✓ Connected" : "";
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
      $("anthropic-status").textContent = "✓ Connected";
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
    $("adzuna-status").textContent = state.connected.adzuna ? "✓ Connected" : "";
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
