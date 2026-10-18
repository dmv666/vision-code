"use strict";
// Prism Loops Studio — interfaz local para editar, previsualizar y renderizar configs de vj.

const $ = (sel) => document.querySelector(sel);
const el = (tag, attrs = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (v === true) n.setAttribute(k, "");
    else if (v !== false && v != null) n.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null) n.append(kid.nodeType ? kid : document.createTextNode(kid));
  return n;
};
const clone = (o) => JSON.parse(JSON.stringify(o));
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* sin almacenamiento: no pasa nada */ } },
};

const state = {
  meta: null, configs: [], path: null, saved: null, cfg: null, tab: "scene",
  phase: 0, hq: false, flip: null, plan: null,
};

// ------------------------------------------------------------------ API
async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).error; } catch { /* cuerpo no JSON */ }
    throw new Error(msg);
  }
  return res.headers.get("Content-Type").includes("json") ? res.json() : res.blob();
}

function banner(msg, ok = false) {
  const b = $("#banner");
  b.hidden = !msg;
  b.textContent = msg || "";
  b.classList.toggle("ok", ok);
}

// ------------------------------------------------------------------ valores por defecto
const D = () => state.meta.defaults;
const get = (obj, path, dflt) => {
  let o = obj;
  for (const k of path.split(".")) { if (o == null || !(k in o)) return dflt; o = o[k]; }
  return o;
};
function set(obj, path, value) {
  const keys = path.split(".");
  let o = obj;
  for (const k of keys.slice(0, -1)) { if (typeof o[k] !== "object" || o[k] === null) o[k] = {}; o = o[k]; }
  o[keys.at(-1)] = value;
}
const val = (path) => get(state.cfg, path, get(D(), path));

// ------------------------------------------------------------------ carga / guardado
async function loadList() {
  state.configs = await api("/api/configs");
  renderList();
}

function renderList() {
  const q = $("#search").value.trim().toLowerCase();
  const nav = $("#config-list");
  nav.replaceChildren();
  const groups = {};
  for (const c of state.configs) {
    const text = `${c.name} ${c.group} ${c.patterns.join(" ")}`.toLowerCase();
    if (q && !text.includes(q)) continue;
    (groups[c.group] ??= []).push(c);
  }
  for (const [g, items] of Object.entries(groups)) {
    nav.append(el("div", { class: "group" }, g));
    for (const c of items) {
      nav.append(el("button", {
        class: "cfg" + (c.path === state.path ? " active" : ""),
        onclick: () => openConfig(c.path),
      }, c.name.replaceAll("_", " "), el("small", {}, c.patterns.join(" + "))));
    }
  }
}

async function openConfig(path) {
  if (isDirty() && !confirm("Hay cambios sin guardar. ¿Descartarlos?")) return;
  const cfg = await api("/api/config?path=" + encodeURIComponent(path));
  state.path = path;
  state.customRes = false;
  state.saved = JSON.stringify(cfg);
  state.cfg = cfg;
  store.set("vj.last", path);
  stopFlip();
  renderAll();
}

const isDirty = () => state.cfg && JSON.stringify(state.cfg) !== state.saved;

async function save(path = state.path) {
  try {
    const r = await api("/api/save", { path, config: state.cfg });
    state.path = r.path;
    state.saved = JSON.stringify(state.cfg);
    await loadList();
    renderHeader();
    banner(`Guardado en configs/${r.path}`, true);
    setTimeout(() => banner(""), 2500);
  } catch (e) { banner("No se pudo guardar: " + e.message); }
}

function renderHeader() {
  $("#file-name").textContent = state.path ? "configs/" + state.path : "—";
  $("#dirty").hidden = !isDirty();
}

// ------------------------------------------------------------------ cambios → previsualización
let previewTimer = null, previewAbort = null, planTimer = null, previewUrl = null;

function changed({ rerender = false } = {}) {
  renderHeader();
  stopFlip();
  if (rerender) renderPanel();
  clearTimeout(previewTimer);
  previewTimer = setTimeout(updatePreview, 220);
  clearTimeout(planTimer);
  planTimer = setTimeout(updatePlan, 220);
  updateOutPath();
}

async function updatePreview() {
  if (!state.cfg) return;
  previewAbort?.abort();
  previewAbort = new AbortController();
  $("#spinner").hidden = false;
  try {
    const res = await fetch("/api/preview", {
      method: "POST", signal: previewAbort.signal, headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config: state.cfg, phase: state.phase, width: state.hq ? 960 : 640, hq: state.hq }),
    });
    if (!res.ok) throw new Error((await res.json()).error);
    const url = URL.createObjectURL(await res.blob());
    $("#preview").src = url;
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = url;
    banner("");
  } catch (e) {
    if (e.name !== "AbortError") banner(e.message);
  } finally {
    $("#spinner").hidden = true;
  }
}

async function updatePlan() {
  try {
    state.plan = await api("/api/plan", { config: state.cfg });
    renderPlan();
    updatePhaseLabel();
  } catch (e) { banner(e.message); }
}

function renderPlan() {
  const p = state.plan, box = $("#plan");
  box.replaceChildren();
  if (!p) return;
  const chip = (label, value) => el("span", { class: "chip" }, label + " ", el("b", {}, value));
  box.append(
    chip("loop", `${p.duration.toFixed(2)} s`), chip("frames", `${p.frames} @ ${p.fps} fps`),
    chip("avance", p.cycles.travel), chip("giros", p.cycles.rotation), chip("oscilación", p.cycles.wobble),
    chip("color", p.cycles.hue), chip("golpes", p.cycles.beats),
  );
  for (const n of p.notes) box.append(el("div", { class: "note" }, "↳ " + n));
  const out = val("output");
  $("#stage").style.aspectRatio = `${out.width} / ${out.height}`;
}

function updatePhaseLabel() {
  const d = state.plan?.duration ?? val("output.duration");
  $("#phase-label").textContent = (state.phase * d).toFixed(1) + " s";
}

// ------------------------------------------------------------------ animación (flipbook)
async function toggleFlip() {
  if (state.flip) return stopFlip();
  const btn = $("#btn-play");
  btn.textContent = "… preparando";
  try {
    const { frames } = await api("/api/flipbook", { config: state.cfg, frames: 36, width: 480 });
    const imgs = frames.map((src) => { const i = new Image(); i.src = src; return i; });
    let k = 0;
    const flip = $("#flip");
    flip.hidden = false;
    state.flip = setInterval(() => { flip.src = imgs[k].src; k = (k + 1) % imgs.length; }, 1000 / 12);
    btn.textContent = "■ Detener";
    btn.title = `Vista rápida: el loop completo en ${(36 / 12).toFixed(0)} s`;
  } catch (e) {
    banner(e.message);
    btn.textContent = "▶ Animar";
  }
}

function stopFlip() {
  if (state.flip) clearInterval(state.flip);
  state.flip = null;
  $("#flip").hidden = true;
  $("#btn-play").textContent = "▶ Animar";
}

// ------------------------------------------------------------------ controles reutilizables
function slider(label, { get: g, set: s, min, max, step, int = false, dflt, onchange }) {
  const v0 = g();
  const range = el("input", { type: "range", min, max, step, value: v0 });
  const num = el("input", { type: "number", min, step, value: v0 });
  const field = el("div", { class: "field" + (dflt !== undefined && v0 !== dflt ? " changed" : "") },
    el("label", {}, el("span", {}, label), dflt !== undefined ? el("span", {}, `def. ${dflt}`) : null),
    el("div", { class: "row" }, range, num));
  const apply = (raw, from) => {
    let v = int ? Math.round(Number(raw)) : Number(raw);
    if (Number.isNaN(v)) return;
    if (from !== range) range.value = v;
    if (from !== num) num.value = v;
    s(v);
    field.classList.toggle("changed", dflt !== undefined && v !== dflt);
    (onchange || changed)();
  };
  range.addEventListener("input", () => apply(range.value, range));
  num.addEventListener("change", () => apply(num.value, num));
  return field;
}

function select(label, options, { get: g, set: s, rerender = false }) {
  const sel = el("select", {}, options.map(([v, t]) =>
    el("option", { value: String(v), selected: String(g()) === String(v) }, t)));
  sel.addEventListener("change", () => {
    const opt = options.find(([v]) => String(v) === sel.value);
    s(opt ? opt[0] : sel.value);
    changed({ rerender });
  });
  return el("div", { class: "field" }, el("label", {}, label), sel);
}

const bindPath = (path) => ({ get: () => val(path), set: (v) => set(state.cfg, path, v) });

// ------------------------------------------------------------------ pestañas
function renderAll() {
  renderHeader();
  renderList();
  renderPanel();
  changed();
}

function renderPanel() {
  for (const b of document.querySelectorAll("#tabs button")) b.classList.toggle("active", b.dataset.tab === state.tab);
  const panel = $("#panel");
  panel.replaceChildren();
  if (!state.cfg) return;
  ({ scene: tabScene, palette: tabPalette, animation: tabAnimation, output: tabOutput,
     post: tabPost, json: tabJson })[state.tab](panel);
}

// ---- Escena: un patrón o varias capas
function patternParams(holder, pattern) {
  const spec = state.meta.patterns[pattern];
  const box = el("div");
  holder.params ??= {};
  for (const [k, m] of Object.entries(spec.params)) {
    box.append(slider(k.replaceAll("_", " "), {
      get: () => holder.params[k] ?? m.default,
      set: (v) => { if (v === m.default) delete holder.params[k]; else holder.params[k] = v; },
      min: m.min, max: m.max, step: m.step, int: m.int, dflt: m.default,
    }));
  }
  return box;
}

const patternOptions = () => Object.keys(state.meta.patterns).map((p) => [p, p.replaceAll("_", " ")]);

function tabScene(panel) {
  const cfg = state.cfg;
  if (!cfg.layers?.length) {
    cfg.geometry ??= { pattern: D().geometry.pattern, params: {} };
    const g = cfg.geometry;
    panel.append(
      el("p", { class: "hint" }, "Un solo patrón. Añade capas para mezclar varios (se suman como luz)."),
      select("Patrón", patternOptions(), {
        get: () => g.pattern, set: (v) => { g.pattern = v; g.params = {}; }, rerender: true,
      }),
      patternParams(g, g.pattern),
      el("button", { onclick: () => {
        cfg.layers = [{ pattern: g.pattern, params: g.params || {} },
                      { pattern: "starfield", opacity: 0.6, params: {} }];
        delete cfg.geometry;
        changed({ rerender: true });
      } }, "+ Añadir capa"),
    );
    return;
  }
  panel.append(el("p", { class: "hint" }, "Capas de abajo arriba. La opacidad es perceptual (como un fader)."));
  cfg.layers.forEach((layer, i) => {
    const move = (d) => {
      const j = i + d;
      if (j < 0 || j >= cfg.layers.length) return;
      [cfg.layers[i], cfg.layers[j]] = [cfg.layers[j], cfg.layers[i]];
      changed({ rerender: true });
    };
    const remove = () => {
      cfg.layers.splice(i, 1);
      if (cfg.layers.length === 1) {               // una sola capa → vuelve a modo patrón
        const only = cfg.layers[0];
        cfg.geometry = { pattern: only.pattern, params: only.params || {} };
        delete cfg.layers;
      }
      changed({ rerender: true });
    };
    const adv = el("textarea", { spellcheck: "false" },
      JSON.stringify({ palette: layer.palette, animation: layer.animation }, null, 2));
    adv.addEventListener("change", () => {
      try {
        const o = JSON.parse(adv.value || "{}");
        for (const k of ["palette", "animation"]) { if (o[k]) layer[k] = o[k]; else delete layer[k]; }
        adv.style.borderColor = "";
        changed();
      } catch { adv.style.borderColor = "var(--bad)"; }
    });
    panel.append(el("div", { class: "card" },
      el("div", { class: "card-head" }, el("h4", {}, `Capa ${i + 1}`),
        el("button", { class: "small ghost", title: "Subir", onclick: () => move(-1) }, "↑"),
        el("button", { class: "small ghost", title: "Bajar", onclick: () => move(1) }, "↓"),
        el("button", { class: "small ghost danger", title: "Quitar", onclick: remove }, "✕")),
      select("Patrón", patternOptions(), {
        get: () => layer.pattern, set: (v) => { layer.pattern = v; layer.params = {}; }, rerender: true,
      }),
      slider("opacidad", { get: () => layer.opacity ?? 1, set: (v) => { layer.opacity = v; },
                           min: 0, max: 1, step: 0.01, dflt: 1 }),
      el("details", {}, el("summary", {}, "Parámetros del patrón"), patternParams(layer, layer.pattern)),
      el("details", {}, el("summary", {}, "Paleta / animación propias (JSON)"), adv,
        el("p", { class: "hint" }, 'Ej.: {"animation": {"speed": 0.5, "beat_multiplier": 2}, "palette": {"preset": "ice"}}')),
    ));
  });
  panel.append(el("button", { onclick: () => {
    cfg.layers.push({ pattern: "starfield", opacity: 0.6, params: {} });
    changed({ rerender: true });
  } }, "+ Añadir capa"));
}

// ---- Paleta
const gradientCss = (cols) => `linear-gradient(90deg, ${[...cols, cols[0]].join(", ")})`;

function tabPalette(panel) {
  const p = (state.cfg.palette ??= {});
  const custom = Array.isArray(p.colors);
  const presets = state.meta.presets;
  const presetName = p.preset in presets ? p.preset : Object.keys(presets)[0];
  panel.append(el("div", { class: "seg" },
    el("button", { class: custom ? "" : "on", onclick: () => {
      delete p.colors; p.preset = presetName; changed({ rerender: true });
    } }, "Preset"),
    el("button", { class: custom ? "on" : "", onclick: () => {
      p.colors = [...(presets[presetName]?.colors || ["#ffffff"])]; changed({ rerender: true });
    } }, "Personalizada")));

  if (!custom) {
    const grid = el("div", { class: "preset-grid" });
    for (const [name, pr] of Object.entries(presets)) {
      grid.append(el("button", {
        class: "preset" + (name === p.preset ? " on" : ""),
        onclick: () => { p.preset = name; delete p.background; changed({ rerender: true }); },
      }, name.replaceAll("_", " "), el("div", { class: "g", style: `background:${gradientCss(pr.colors)}` })));
    }
    panel.append(grid);
  } else {
    const sw = el("div", { class: "swatches" });
    p.colors.forEach((c, i) => {
      const inp = el("input", { type: "color", value: c });
      inp.addEventListener("input", () => { p.colors[i] = inp.value; changed(); grad.style.background = gradientCss(p.colors); });
      sw.append(el("span", { class: "swatch" }, inp, p.colors.length > 1 ? el("button", {
        class: "small ghost", title: "Quitar", onclick: () => { p.colors.splice(i, 1); changed({ rerender: true }); },
      }, "✕") : null));
    });
    if (p.colors.length < 8) sw.append(el("button", { class: "small", onclick: () => {
      p.colors.push(p.colors.at(-1)); changed({ rerender: true });
    } }, "+ color"));
    const grad = el("div", { class: "gradient", style: `background:${gradientCss(p.colors)}` });
    panel.append(el("p", { class: "hint" }, "Gradiente cíclico: el último color enlaza con el primero."), sw, grad);
  }

  const bgDefault = presets[p.preset]?.background || "#000000";
  const bg = el("input", { type: "color", value: p.background || bgDefault });
  bg.addEventListener("input", () => { p.background = bg.value; changed(); });
  panel.append(
    el("div", { class: "field" }, el("label", {}, "Fondo"), el("div", { class: "row" }, bg,
      el("button", { class: "small ghost", onclick: () => { delete p.background; changed({ rerender: true }); } }, "por defecto"))),
    slider("Intensidad", { get: () => p.intensity ?? 1, set: (v) => { p.intensity = v; },
                           min: 0, max: 3, step: 0.01, dflt: 1 }),
  );
}

// ---- Animación
function tabAnimation(panel) {
  const synced = val("animation.bars") != null;
  panel.append(el("div", { class: "field" },
    el("label", { class: "toggle" }, el("input", { type: "checkbox", checked: synced, onchange: (e) => {
      set(state.cfg, "animation.bars", e.target.checked ? 8 : null);
      if (e.target.checked && !val("animation.bpm")) set(state.cfg, "animation.bpm", 120);
      changed({ rerender: true });
    } }), "Duración en compases (loop sincronizado al BPM)")));
  if (synced) {
    panel.append(
      slider("Compases", { ...bindPath("animation.bars"), min: 1, max: 64, step: 1, int: true }),
      slider("Tiempos por compás", { ...bindPath("animation.beats_per_bar"), min: 2, max: 8, step: 1, int: true }),
    );
  }
  for (const f of state.meta.sections.animation) {
    panel.append(slider(f.label, { ...bindPath("animation." + f.key), min: f.min, max: f.max, step: f.step,
                                   int: f.step === 1, dflt: get(D(), "animation." + f.key) }));
  }
  panel.append(el("p", { class: "hint" },
    "Cada movimiento se ajusta a un número entero de ciclos por loop para que cierre perfecto; " +
    "los redondeos aparecen bajo la vista previa."));
}

// ---- Salida
function tabOutput(panel) {
  const m = state.meta, w = val("output.width"), h = val("output.height");
  // "Personalizada" es un modo de la interfaz: aunque el tamaño coincida con un
  // preset, el usuario quiere ver los campos de ancho y alto.
  const preset = state.customRes ? null : m.resolutions.find((r) => r.width === w && r.height === h);
  panel.append(select("Resolución", [...m.resolutions.map((r) => [r.label, `${r.label} — ${r.width}×${r.height}`]),
                                      ["custom", "Personalizada"]], {
    get: () => preset ? preset.label : "custom",
    set: (v) => {
      const r = m.resolutions.find((x) => x.label === v);
      state.customRes = !r;
      if (r) { set(state.cfg, "output.width", r.width); set(state.cfg, "output.height", r.height); }
    },
    rerender: true,
  }));
  if (!preset) {
    panel.append(
      slider("Ancho", { ...bindPath("output.width"), min: 256, max: 7680, step: 2, int: true }),
      slider("Alto", { ...bindPath("output.height"), min: 256, max: 4320, step: 2, int: true }),
    );
  }
  panel.append(select("FPS", m.fps.map((f) => [f, `${f} fps`]), bindPath("output.fps")));
  const synced = val("animation.bars") != null;
  if (synced) panel.append(el("p", { class: "hint" }, "La duración la fijan los compases (pestaña Animación)."));
  else panel.append(slider("Duración (s)", { ...bindPath("output.duration"), min: 1, max: 120, step: 0.5 }));
  const codec = val("output.codec");
  panel.append(
    select("Codec", [["h264", "H.264 (universal)"], ["hevc", "HEVC 10 bits (menos banding)"], ["prores", "ProRes (.mov, máster)"]], {
      ...bindPath("output.codec"), rerender: true,
      set: (v) => { set(state.cfg, "output.codec", v); if (!m.qualities[v].includes(val("output.quality"))) set(state.cfg, "output.quality", v === "prores" ? "hq" : "high"); },
    }),
    select("Calidad", m.qualities[codec].map((q) => [q, q]), bindPath("output.quality")),
    select("Codificación por hardware", [["auto", "Automática (sí en Mac)"], [true, "Sí"], [false, "No (software)"]], bindPath("output.hardware")),
    slider("Supersampling (anti-aliasing)", { ...bindPath("output.supersample"), min: 1, max: 3, step: 1, int: true, dflt: 2 }),
    slider("Motion blur: muestras", { ...bindPath("output.motion_blur.samples"), min: 1, max: 8, step: 1, int: true, dflt: 1 }),
    slider("Motion blur: obturador", { ...bindPath("output.motion_blur.shutter"), min: 0, max: 1, step: 0.05, dflt: 0.5 }),
    el("p", { class: "hint" }, "Supersampling y motion blur multiplican el tiempo de render; la vista previa los omite salvo con «Calidad final»."),
  );
}

// ---- Post
function tabPost(panel) {
  for (const f of state.meta.sections.post) {
    panel.append(slider(f.label, { ...bindPath("post." + f.key), min: f.min, max: f.max, step: f.step,
                                   dflt: get(D(), "post." + f.key) }));
  }
}

// ---- JSON
function tabJson(panel) {
  const ta = el("textarea", { id: "json-area", spellcheck: "false" }, JSON.stringify(state.cfg, null, 2));
  panel.append(ta, el("div", { class: "row", style: "margin-top:8px;display:flex;gap:8px" },
    el("button", { onclick: () => {
      try { state.cfg = JSON.parse(ta.value); changed(); banner("JSON aplicado", true); setTimeout(() => banner(""), 1500); }
      catch (e) { banner("JSON inválido: " + e.message); }
    } }, "Aplicar")));
}

// ------------------------------------------------------------------ renders
function defaultOutPath() {
  const name = (state.path || "loop").split("/").pop().replace(/\.json$/, "");
  return `renders/${name}${state.plan?.container || ".mp4"}`;
}

function updateOutPath() {
  const inp = $("#out-path");
  if (!inp.dataset.touched) inp.value = state.cfg?.output?.path && !state.cfg.output.path.startsWith("renders/loop")
    ? state.cfg.output.path.replace(/\.(mp4|mov)$/, "") + (state.plan?.container || ".mp4")
    : defaultOutPath();
}

async function startRender() {
  const btn = $("#btn-render");
  btn.disabled = true;
  try {
    const name = (state.path || "sin guardar").split("/").pop().replace(/\.json$/, "");
    await api("/api/render", { config: state.cfg, output: $("#out-path").value, name });
    pollJobs(true);
  } catch (e) { banner("No se pudo iniciar el render: " + e.message); }
  finally { btn.disabled = false; }
}

const fmtTime = (s) => s == null ? "—" : s >= 3600 ? `${(s / 3600).toFixed(1)} h` : s >= 60 ? `${Math.floor(s / 60)} min ${Math.round(s % 60)} s` : `${Math.round(s)} s`;

let jobsTimer = null;
async function pollJobs(soon = false) {
  clearTimeout(jobsTimer);
  let jobs = [];
  try { jobs = await api("/api/jobs"); } catch { /* servidor ocupado: reintenta */ }
  renderJobs(jobs);
  const active = jobs.some((j) => ["en cola", "renderizando", "cancelando"].includes(j.state));
  jobsTimer = setTimeout(pollJobs, active || soon ? 1000 : 5000);
}

function renderJobs(jobs) {
  const box = $("#jobs");
  box.replaceChildren();
  for (const j of [...jobs].reverse()) {
    const pct = j.total ? (100 * j.frame / j.total) : (j.state === "listo" ? 100 : 0);
    const elapsed = j.started ? ((j.finished || Date.now() / 1000) - j.started) : null;
    const actions = [];
    if (["en cola", "renderizando"].includes(j.state))
      actions.push(el("button", { class: "small ghost danger", onclick: () => api("/api/cancel", { id: j.id }).then(() => pollJobs(true)) }, "Cancelar"));
    if (j.state === "listo")
      actions.push(el("button", { class: "small", onclick: () => api("/api/reveal", { path: j.output }).catch((e) => banner(e.message)) }, "Mostrar en Finder"));
    box.append(el("div", { class: "job" },
      el("div", { class: "job-head" }, el("span", { class: "name" }, j.name),
        el("span", { class: "badge " + j.state }, j.state), ...actions),
      el("div", { class: "bar" }, el("div", { style: `width:${pct.toFixed(1)}%` })),
      el("div", { class: "job-meta" },
        el("span", {}, j.total ? `frame ${j.frame}/${j.total}` : ""),
        el("span", {}, j.fps ? `${j.fps.toFixed(1)} fps` : ""),
        el("span", {}, j.state === "renderizando" ? `quedan ${fmtTime(j.eta)}` : elapsed ? `tardó ${fmtTime(elapsed)}` : ""),
        el("span", {}, j.encoder), el("span", { class: "mono" }, j.output.split("/").slice(-2).join("/"))),
      j.state === "error" ? el("pre", {}, j.log.join("\n")) : null,
    ));
  }
}

// ------------------------------------------------------------------ comprobar loop
async function checkLoop() {
  const btn = $("#btn-check");
  btn.disabled = true;
  btn.textContent = "Comprobando…";
  try {
    const r = await api("/api/check", { config: state.cfg });
    banner(r.ok
      ? `✓ Loop perfecto: el frame N es idéntico al 0 (máx ${r.max}/255). Costura ${r.seam.toFixed(2)} vs paso normal ${r.step.toFixed(2)}.`
      : `✗ El loop tiene un salto: ${r.bad} valores de píxel difieren más de 2/255 (máx ${r.max}).`, r.ok);
  } catch (e) { banner(e.message); }
  finally { btn.disabled = false; btn.textContent = "Comprobar loop"; }
}

// ------------------------------------------------------------------ arranque
async function init() {
  state.meta = await api("/api/meta");
  $("#gpu").textContent = state.meta.gpu_error ? "Sin GPU: " + state.meta.gpu_error : "GPU: " + state.meta.gpu;
  await loadList();
  const last = store.get("vj.last");
  const first = state.configs.find((c) => c.path === last) || state.configs[0];
  if (first) await openConfig(first.path);
  pollJobs();

  $("#search").addEventListener("input", renderList);
  $("#tabs").addEventListener("click", (e) => {
    const t = e.target.closest("button");
    if (t) { state.tab = t.dataset.tab; renderPanel(); }
  });
  $("#phase").addEventListener("input", (e) => {
    state.phase = Number(e.target.value);
    updatePhaseLabel();
    stopFlip();
    clearTimeout(previewTimer);
    previewTimer = setTimeout(updatePreview, 60);
  });
  $("#hq").addEventListener("change", (e) => { state.hq = e.target.checked; updatePreview(); });
  $("#btn-play").addEventListener("click", toggleFlip);
  $("#btn-check").addEventListener("click", checkLoop);
  $("#btn-render").addEventListener("click", startRender);
  $("#out-path").addEventListener("input", (e) => { e.target.dataset.touched = "1"; });
  $("#btn-save").addEventListener("click", () => state.path ? save() : openSaveAs());
  $("#btn-saveas").addEventListener("click", openSaveAs);
  $("#btn-revert").addEventListener("click", () => {
    if (!state.saved) return;
    state.cfg = JSON.parse(state.saved);
    renderAll();
  });
  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "s") { e.preventDefault(); state.path ? save() : openSaveAs(); }
  });
  window.addEventListener("beforeunload", (e) => { if (isDirty()) e.preventDefault(); });
}

function openSaveAs() {
  const dlg = $("#dlg-saveas");
  const cur = state.path || "mine/nuevo.json";
  const parts = cur.split("/");
  $("#saveas-folder").value = parts.length > 1 ? (parts[0] === "chill" || parts[0] === "showcase" ? "mine" : parts[0]) : "mine";
  $("#saveas-name").value = parts.at(-1).replace(/\.json$/, "") + "_v2";
  dlg.showModal();
  dlg.onclose = () => {
    if (dlg.returnValue !== "ok") return;
    const folder = $("#saveas-folder").value.trim().replace(/[^A-Za-z0-9_\-]/g, "");
    const name = $("#saveas-name").value.trim().replace(/[^A-Za-z0-9_\-]/g, "");
    if (name) save(`${folder ? folder + "/" : ""}${name}.json`);
  };
}

init().catch((e) => banner("No se pudo iniciar la interfaz: " + e.message));
