// Care Circle web app. Vanilla ES module. Every string from the server or from OCR is untrusted, so it is escaped before it reaches innerHTML.
const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const HOUR = 3600e3;
const TABS = [
  ["today", "Today", "M4 6h16M4 12h16M4 18h10"],
  ["add", "Add", "M12 5v14M5 12h14"],
  ["circle", "Circle", "M8 11a3 3 0 100-6 3 3 0 000 6zm8 0a3 3 0 100-6 3 3 0 000 6zM2 20c0-3 3-5 6-5s6 2 6 5m2-5c3 0 6 2 6 5"],
  ["graph", "Graph", "M6 6a2 2 0 100-4 2 2 0 000 4zm12 4a2 2 0 100-4 2 2 0 000 4zM8 20a2 2 0 100-4 2 2 0 000 4zM7.5 5l9 3M7 6l1 10"],
  ["history", "History", "M12 7v5l3 2M3 12a9 9 0 109-9 9 9 0 00-7 3.4M3 4v4h4"],
  ["doses", "Doses", "M4 12l5 5L20 6"],
];
const st = { s: null, as: null, tab: "today", warp: 0, data: {}, props: [] };

try { st.s = JSON.parse(localStorage.getItem("cc-session") || "null"); } catch { st.s = null; }
if (st.s) st.as = st.s.as || Object.keys(st.s.keys)[0];

function save() { try { localStorage.setItem("cc-session", JSON.stringify({ ...st.s, as: st.as })); } catch {} }
function toast(msg) {
  const t = document.createElement("div"); t.className = "toast"; t.textContent = msg; t.setAttribute("role", "status");
  document.body.append(t); setTimeout(() => t.remove(), 3200);
}
async function api(op, args = {}) {
  const r = await fetch(`/v1/tenants/${st.s.circle}/${op}`, {
    method: "POST", headers: { "content-type": "application/json", authorization: `Bearer ${st.s.keys[st.as]}` }, body: JSON.stringify(args),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || j.error || r.statusText);
  return j.result;
}
const person = () => st.s.person;
const nowMs = () => Date.now() + st.warp * HOUR;

// ------------------------------------------------------------------ views
const pill = (cls, t) => `<span class="pill ${cls}">${esc(t)}</span>`;
const sevCls = (l) => (/major/i.test(l) ? "major" : /minor/i.test(l) ? "minor" : "");

function flagsHtml(c) {
  const out = [];
  for (const f of c.direct) out.push(`<div class="flag ${sevCls(f.level)}"><b>${esc(f.drugs[0])} + ${esc(f.drugs[1])}</b> ${pill(f.level === "Major" ? "bad" : "warn", f.level)}
    <div class="src">Source: ${esc(f.source)}</div><code>(a:Drug)-[:INTERACTS {level:'${esc(f.level)}'}]-(b:Drug)</code></div>`);
  for (const f of c.enzyme_paths) out.push(`<div class="flag"><b>${esc(f.meaning)}</b> ${pill("info", "enzyme path")}
    <div class="src">${esc(f.source)}${f.also_in_ddinter ? " · also in DDInter" : ""}</div><code>${esc(f.path)}</code></div>`);
  for (const f of c.unrated) out.push(`<div class="flag minor"><b>${esc(f.drugs[0])} + ${esc(f.drugs[1])}</b> ${pill("mute", "listed, severity unrated")}
    <div class="src">Unrated is not the same as safe. Source: ${esc(f.source)}</div></div>`);
  return out.join("");
}
function judgementHtml(c) {
  const j = c.judgement, tone = { flags: "bad", partial: "warn", no_data: "mute", no_known_conflict: "ok" }[j.state] || "mute";
  const r = c.regimen_risk;
  return `<div class="card"><div class="verdict"><span class="dot" style="background:var(--${tone === "mute" ? "label2" : tone})"></span><div>
    <div class="big">${esc(j.statement)}</div>${j.reasons.map((x) => `<div class="muted">${esc(x)}</div>`).join("")}
    ${r != null ? `<div class="muted" style="margin-top:.75rem">Combined flag weight (assumed weights, noisy-OR): ${(r * 100).toFixed(0)}%</div>
      <div class="bar" aria-hidden="true"><i style="width:${Math.min(100, r * 100)}%;background:var(--${r > 0.6 ? "bad" : "warn"})"></i></div>` : ""}
    <div class="muted" style="margin-top:.5rem">${esc(c.notice)}</div></div></div></div>`;
}

async function viewToday() {
  const c = await api("care_check", { person: person() });
  const reg = c.regimen.map((r) => `<div class="drug"><div><b>${esc(r.drug)}</b> ${esc(r.dose_text)} ${esc(r.freq_text)}
    <div class="src">added by ${esc(r.by)} · ${esc(r.source)}${r.quote ? ` · “${esc(r.quote)}”` : ""}</div></div></div>`).join("");
  return `${judgementHtml(c)}<div class="card"><h2>On record for ${esc(person())}</h2>${reg || '<p class="muted">Nothing yet. Add a medicine from the Add tab.</p>'}</div>
    ${c.direct.length + c.enzyme_paths.length + c.unrated.length ? `<div class="card"><h2>Flags, with sources</h2>${flagsHtml(c)}</div>` : ""}`;
}

async function viewAdd() {
  const cards = st.props.map((p, i) => proposalHtml(p, i)).join("");
  return `<div class="card"><h2>Add from a photo, voice note, document or text</h2>
    <label class="drop" id="drop" tabindex="0"><input id="file" type="file" hidden accept="image/*,audio/*,.pdf,.docx,.txt">
      <div><b>Drop a file or tap to choose</b></div><div class="muted">Photo of a label · voice note · PDF · Word</div></label>
    <div class="row wrapx" style="margin-top:.75rem"><button class="btn ghost small" id="sample">Use a sample label</button>
      <button class="btn ghost small" id="rec">Record a voice note</button></div>
    <p class="muted">Or type it:</p><textarea id="txt" rows="3" placeholder="e.g. Clarithromycin 500 mg twice daily for 7 days"></textarea>
    <div class="row" style="margin-top:.75rem"><button class="btn" id="go">Read it</button><span id="busy"></span></div>
    <p class="muted">Nothing is saved until you confirm each item. Readings come with the exact line they came from.</p></div>
    <div id="props">${cards}</div>`;
}
function proposalHtml(p, i) {
  const cands = p.drug_candidates.map((c, k) => `<option value="${esc(c.name)}" ${k === 0 ? "selected" : ""}>${esc(c.name)}</option>`).join("");
  return `<div class="card" data-i="${i}"><div class="row wrapx">${p.verified ? pill("ok", "quote verified") : pill("warn", "quote not found in source")}
    ${pill("mute", p.method)}</div>
    <p class="cy" style="font-family:inherit;font-size:.875rem">“${esc(p.quote)}”</p>
    <div class="cols two"><label class="muted">Medicine<select class="drugsel">${cands}</select></label>
      <label class="muted">For<input type="text" class="forwho" value="${esc(person())}"></label>
      <label class="muted">Dose<input type="text" class="dose" value="${esc(p.dose_text)}"></label>
      <label class="muted">How often<input type="text" class="freq" value="${esc(p.freq_text)}"></label></div>
    <div class="row" style="margin-top:.75rem"><button class="btn small ok-btn">Confirm</button><button class="btn ghost small no-btn">Discard</button></div></div>`;
}
function bindAdd() {
  const drop = $("#drop"), file = $("#file");
  const busy = (on) => ($("#busy").innerHTML = on ? '<span class="spin"></span>' : "");
  const run = async (fd, name) => {
    busy(true);
    try {
      const r = await fetch(`/v1/tenants/${st.s.circle}/intake`, { method: "POST", headers: { authorization: `Bearer ${st.s.keys[st.as]}` }, body: fd });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || "failed");
      st.props = j.proposals; st.lastText = j.text;
      st.srcType = { image: "photo", voice: "voice", document: "document" }[j.source.kind] || "typed";
      if (!j.proposals.length) toast(j.source.note || "No medicine found. Try typing it.");
      render("add");
    } catch (e) { toast("Could not read that: " + e.message); } finally { busy(false); }
  };
  drop.addEventListener("click", () => file.click());
  drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") file.click(); });
  ["dragover", "dragenter"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, () => drop.classList.remove("over")));
  drop.addEventListener("drop", (e) => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) { const fd = new FormData(); fd.append("file", f); run(fd); } });
  file.addEventListener("change", () => { const f = file.files[0]; if (f) { const fd = new FormData(); fd.append("file", f); run(fd); } });
  $("#sample").addEventListener("click", async () => {
    const b = await (await fetch("/demo/label.png")).blob(); const fd = new FormData(); fd.append("file", new File([b], "label.png", { type: "image/png" })); run(fd);
  });
  $("#go").addEventListener("click", () => { const t = $("#txt").value.trim(); if (!t) return toast("Type something first"); const fd = new FormData(); fd.append("text", t); run(fd); });
  $("#rec").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    if (btn._rec) { btn._rec.stop(); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true }); const chunks = [], rec = new MediaRecorder(stream);
      btn._rec = rec; btn.textContent = "Stop recording";
      rec.ondataavailable = (ev) => chunks.push(ev.data);
      rec.onstop = () => { stream.getTracks().forEach((t) => t.stop()); btn._rec = null; btn.textContent = "Record a voice note";
        const fd = new FormData(); fd.append("file", new File([new Blob(chunks)], "note.webm", { type: "audio/webm" })); run(fd); };
      rec.start();
    } catch { toast("Microphone not available"); }
  });
  document.querySelectorAll("#props .card").forEach((card) => {
    const i = +card.dataset.i, p = st.props[i];
    card.querySelector(".no-btn").addEventListener("click", () => { st.props.splice(i, 1); render("add"); });
    card.querySelector(".ok-btn").addEventListener("click", async () => {
      try {
        const r = await api("care_record", { person: card.querySelector(".forwho").value, drug: card.querySelector(".drugsel").value,
          dose_text: card.querySelector(".dose").value, freq_text: card.querySelector(".freq").value,
          source_type: st.srcType || "photo", quote: p.quote, source_text: st.lastText || p.quote, confirm: false });
        await api("care_confirm", { dose_id: r.id });
        st.props.splice(i, 1); toast("Saved. The other carers will be asked to acknowledge it."); render("add");
      } catch (e) { toast(e.message); }
    });
  });
}

async function viewCircle() {
  const d = await api("care_divergence", { person: person(), now: nowMs() });
  const n = await api("care_nudges", { person: person(), now: nowMs() }).catch(() => []);
  const rows = Object.entries(d.carers).map(([c, v]) => `<div style="margin:.75rem 0"><div class="row"><b style="text-transform:capitalize">${esc(c)}</b><span class="grow"></span>
    ${v.unacknowledged.length ? pill("warn", `${v.unacknowledged.length} not seen`) : pill("ok", "up to date")}</div>
    <div class="bar" title="divergence"><i style="width:${(v.divergence * 100).toFixed(0)}%;background:var(--${v.divergence > 0.5 ? "bad" : "warn"})"></i></div>
    ${v.unacknowledged.map((u) => `<div class="drug"><div><b>${esc(u.drug)}</b> ${esc(u.action)}<div class="src">${u.age_hours} h ago</div></div>
      ${c === st.as ? `<button class="btn small" data-ack="${esc(u.dose)}">I have seen this</button>` : ""}</div>`).join("")}</div>`).join("");
  return `<div class="card"><h2>Who is out of date</h2>
    <p class="muted">${d.most_out_of_date ? `${esc(d.most_out_of_date)} is furthest behind.` : "Everyone has seen every change."} Older unseen changes count more (half-life ${d.half_life_hours} h, an assumption).</p>${rows}</div>
    <div class="card"><h2>Time warp</h2><p class="muted">Pretend it is later, to see reminders fire. Now + <b id="wv">${st.warp}</b> h</p>
      <input type="range" id="warp" min="0" max="48" step="1" value="${st.warp}" style="width:100%"></div>
    <div class="card"><h2>Reminders due</h2>${n.map((x) => `<div class="drug"><div>${esc(x.message.text)}<div class="src">to ${esc(x.notify)} · ${esc(x.kind)} · sent once</div></div></div>`).join("") || '<p class="muted">None due.</p>'}</div>`;
}

async function viewGraph() {
  const h = await api("care_hubs", { person: person() });
  const c = await api("care_check", { person: person() });
  const drugs = c.regimen.map((r) => r.drug), N = drugs.length, cx = 160, cy = 130, R = 95;
  const pos = Object.fromEntries(drugs.map((d, i) => [d, [cx + R * Math.cos((2 * Math.PI * i) / N - Math.PI / 2), cy + R * Math.sin((2 * Math.PI * i) / N - Math.PI / 2)]]));
  const col = (l) => (/major/i.test(l) ? "var(--bad)" : /moderate/i.test(l) ? "var(--warn)" : "var(--info)");
  const lines = [...c.direct.map((f) => [f.drugs, col(f.level), 2.5]),
    ...c.enzyme_paths.map((f) => [f.path.split(" -")[0] && [f.path.split(" -")[0], f.path.split("SUBSTRATE_OF- ")[1]], "var(--info)", 1.5])]
    .filter(([p]) => p && pos[p[0]] && pos[p[1]])
    .map(([p, color, w]) => `<line x1="${pos[p[0]][0]}" y1="${pos[p[0]][1]}" x2="${pos[p[1]][0]}" y2="${pos[p[1]][1]}" stroke="${color}" stroke-width="${w}" stroke-linecap="round"/>`).join("");
  const nodes = drugs.map((d) => `<g><circle cx="${pos[d][0]}" cy="${pos[d][1]}" r="7" fill="var(--accent)"/><text x="${pos[d][0]}" y="${pos[d][1] - 12}" text-anchor="middle">${esc(d)}</text></g>`).join("");
  return `<div class="card"><h2>This regimen as a graph</h2>
    <svg class="graph" viewBox="0 0 320 260" role="img" aria-label="Medicines as nodes, interactions as lines">${lines}${nodes}</svg>
    <div class="muted">Red = major · amber = moderate · blue = enzyme path or minor</div></div>
    <div class="card"><h2>Most hazard-connected in this regimen</h2>${h.regimen_hubs.rows.map((r) => `<div class="drug"><b>${esc(r.drug)}</b><span>${r.hazards_in_regimen} hazard(s)</span></div>`).join("") || '<p class="muted">No hazard edges inside this regimen.</p>'}
      <code class="cy">${esc(h.regimen_hubs.cypher)}</code></div>
    <div class="card"><h2>Hub medicines across the whole reference graph</h2><p class="muted">PageRank over moderate/major interaction edges.</p>
      ${h.global_hubs.rows.map((r, i) => `<div class="drug"><span>${i + 1}. <b>${esc(r.drug)}</b></span><span class="muted">${r.score}</span></div>`).join("")}
      <code class="cy">${esc(h.global_hubs.cypher)}</code></div>`;
}

async function viewHistory() {
  const span = 14 * 24, back = st.back ?? 0, t = Date.now() - back * HOUR;
  const [reg, c] = await Promise.all([api("care_regimen", { person: person(), as_of: t }), api("care_check", { person: person(), as_of: t })]);
  return `<div class="card"><h2>What did we know then?</h2><p class="muted">${back ? `${(back / 24).toFixed(1)} days ago · ${new Date(t).toLocaleString()}` : "Now"}</p>
    <input type="range" id="back" min="0" max="${span}" step="1" value="${back}" style="width:100%;direction:rtl"></div>
    <div class="card"><h2>Regimen at that time</h2>${reg.map((r) => `<div class="drug"><div><b>${esc(r.drug)}</b> ${esc(r.dose_text)} ${esc(r.freq_text)}<div class="src">by ${esc(r.by)}</div></div></div>`).join("") || '<p class="muted">Nothing on record then.</p>'}</div>
    ${judgementHtml(c)}`;
}

async function viewDoses() {
  const reg = await api("care_regimen", { person: person() });
  const log = await api("care_gives", { person: person() });
  const slot = new Date().toISOString().slice(0, 10) + " 08:00";
  return `<div class="card"><h2>Record a dose given</h2><p class="muted">A slot can be recorded once. If two carers try, the second is told who already did.</p>
    <div class="cols two"><label class="muted">Medicine<select id="gd">${reg.map((r) => `<option>${esc(r.drug)}</option>`).join("")}</select></label>
    <label class="muted">Slot<input type="text" id="gs" value="${slot}"></label></div>
    <div class="row" style="margin-top:.75rem"><button class="btn" id="gg">Record as ${esc(st.as)}</button></div><div id="gmsg" class="muted" style="margin-top:.5rem"></div></div>
    <div class="card"><h2>Recorded</h2>${log.map((g) => `<div class="drug"><div><b>${esc(g.drug)}</b> ${esc(g.slot)}<div class="src">by ${esc(g.by)}</div></div></div>`).join("") || '<p class="muted">Nothing yet.</p>'}</div>`;
}

const VIEWS = { today: viewToday, add: viewAdd, circle: viewCircle, graph: viewGraph, history: viewHistory, doses: viewDoses };

function bind(tab) {
  if (tab === "add") bindAdd();
  if (tab === "circle") {
    document.querySelectorAll("[data-ack]").forEach((b) => b.addEventListener("click", async () => { try { await api("care_ack", { dose_id: b.dataset.ack }); toast("Acknowledged"); render("circle"); } catch (e) { toast(e.message); } }));
    const w = $("#warp"); w?.addEventListener("input", () => ($("#wv").textContent = w.value)); w?.addEventListener("change", () => { st.warp = +w.value; render("circle"); });
  }
  if (tab === "history") { const b = $("#back"); b?.addEventListener("change", () => { st.back = +b.value; render("history"); }); }
  if (tab === "doses") $("#gg")?.addEventListener("click", async () => {
    try {
      const r = await api("care_give", { person: person(), drug: $("#gd").value, slot: $("#gs").value });
      if (r.given) { toast("Recorded"); render("doses"); } else $("#gmsg").textContent = `Already recorded by ${r.already_given_by}. ${r.note}`;
    } catch (e) { toast(e.message); }
  });
}

// ------------------------------------------------------------------ shell
function hero() {
  $("#app").innerHTML = `<div class="hero"><div class="big">One shared, verified memory of a loved one's medicines.</div>
    <p>Care Circle records what each carer adds, checks it against public interaction data, and tells everyone who has not seen a change. It records and cross-checks. It never says what to take or stop.</p>
    <button class="btn" id="start">Start a demo circle</button><p class="muted">All data is synthetic. No real people or records.</p></div>`;
  $("#start").addEventListener("click", async (e) => {
    e.currentTarget.disabled = true;
    try {
      const j = await (await fetch("/demo/start", { method: "POST" })).json();
      st.s = { circle: j.circle, person: j.person, keys: j.keys }; st.as = Object.keys(j.keys)[0]; save(); shell();
    } catch { toast("Could not start the demo"); e.currentTarget.disabled = false; }
  });
}
function shell() {
  const who = $("#who"), tabs = $("#tabs");
  if (!st.s) { who.hidden = tabs.hidden = true; return hero(); }
  who.hidden = tabs.hidden = false;
  who.innerHTML = Object.keys(st.s.keys).map((k) => `<button aria-pressed="${k === st.as}" data-k="${esc(k)}">${esc(k.split("-")[0])}</button>`).join("");
  who.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { st.as = b.dataset.k; save(); shell(); }));
  $("#sub").textContent = `Synthetic data · acting as ${st.as.split("-")[0]}`;
  tabs.firstElementChild.innerHTML = TABS.map(([k, l, d]) => `<button role="tab" data-t="${k}" aria-selected="${k === st.tab}">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="${d}"/></svg>${l}</button>`).join("");
  tabs.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { st.tab = b.dataset.t; shell(); }));
  render(st.tab);
}
async function render(tab) {
  st.tab = tab;
  $("#tabs").querySelectorAll("button").forEach((b) => b.setAttribute("aria-selected", b.dataset.t === tab));
  const app = $("#app");
  try {
    app.innerHTML = `<div class="banner">Care Circle records and cross-checks. It never advises: talk to a prescriber or pharmacist about any change.</div>${await VIEWS[tab]()}`;
    bind(tab);
  } catch (e) {
    app.innerHTML = `<div class="card"><h2>Something went wrong</h2><p class="muted">${esc(e.message)}</p>${/401|403|key|auth/i.test(e.message) ? '<button class="btn" id="reset">Start over</button>' : ""}</div>`;
    $("#reset")?.addEventListener("click", () => { try { localStorage.removeItem("cc-session"); } catch {} st.s = null; shell(); });
  }
}
shell();
