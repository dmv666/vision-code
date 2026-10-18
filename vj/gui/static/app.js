"use strict";
// Prism Loops Studio — editar, previsualizar, variar y renderizar escenas de vj.

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
const encPath = (p) => p.split("/").map(encodeURIComponent).join("/");
const BUILTIN_GROUPS = ["básicas", "chill", "showcase"];

const state = {
  me: null, meta: null, configs: [], path: null, saved: null, cfg: null, tab: "scene", view: "editor",
  phase: 0, hq: false, plan: null, customRes: false, suggestName: null,
  playing: false, clip: null,
  undo: [], redo: [], histCur: null,
  renders: [], jobs: [], jobStates: {},
};

// ------------------------------------------------------------------ API
async function api(path, body, { signal } = {}) {
  const res = await fetch(path, body === undefined ? { signal } : {
    method: "POST", signal, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (res.status === 401 && path !== "/api/login") { showLogin(); throw new Error("inicia sesión"); }
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).error; } catch { /* cuerpo no JSON */ }
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  return (res.headers.get("Content-Type") || "").includes("json") ? res.json() : res.blob();
}

function banner(msg, ok = false) {
  const b = $("#banner");
  b.hidden = !msg;
  b.textContent = msg || "";
  b.classList.toggle("ok", ok);
}

function toast(msg, kind = "", action = null, ms = 4500) {
  const t = el("div", { class: "toast " + kind }, el("span", {}, msg),
    action ? el("button", { class: "small", onclick: () => { action.fn(); t.remove(); } }, action.label) : null,
    el("button", { class: "small ghost", title: "Cerrar", onclick: () => t.remove() }, "✕"));
  $("#toasts").append(t);
  if (ms) setTimeout(() => t.remove(), ms);
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
const isAdmin = () => !!state.me?.user?.admin;
const limits = () => state.me?.limits;

// ------------------------------------------------------------------ acceso
function showLogin() {
  $("#login").hidden = false;
  $("#login-name").value = store.get("vj.name") || "";
  ($("#login-name").value ? $("#login-code") : $("#login-name")).focus();
}

async function doLogin(e) {
  e.preventDefault();
  const err = $("#login-error");
  err.hidden = true;
  try {
    await api("/api/login", { name: $("#login-name").value, code: $("#login-code").value });
    store.set("vj.name", $("#login-name").value);
    location.reload();
  } catch (ex) { err.textContent = ex.message; err.hidden = false; }
}

// ------------------------------------------------------------------ lista de escenas
async function loadList() {
  state.configs = await api("/api/configs");
  renderList();
}

const configInfo = (path) => state.configs.find((c) => c.path === path);

function displayPath(path) {
  if (!path) return state.cfg ? "Escena sin guardar" : "—";
  const me = state.me.user.name;
  if (path.startsWith(`users/${me}/`)) return "mis escenas / " + path.split("/").pop().replace(/\.json$/, "");
  return "configs/" + path;
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
  if (!Object.keys(groups).length) nav.append(el("p", { class: "hint", style: "padding:0 8px" }, "Nada coincide."));
  for (const [g, items] of Object.entries(groups)) {
    nav.append(el("div", { class: "group" }, g));
    for (const c of items) {
      const deletable = c.writable && !BUILTIN_GROUPS.includes(c.group);
      nav.append(el("button", {
        class: "cfg" + (c.path === state.path ? " active" : ""), title: c.path,
        onclick: () => openConfig(c.path),
      },
        el("img", { class: "thumb", loading: "lazy", alt: "", src: `/api/thumb?config=${encodeURIComponent(c.path)}&v=${c.mtime}`,
                    onerror: (e) => { e.target.style.visibility = "hidden"; } }),
        el("span", { class: "txt" }, c.name.replaceAll("_", " "), el("small", {}, c.patterns.join(" + "))),
        deletable ? el("span", { class: "del" }, el("button", {
          class: "small ghost danger", title: "Borrar escena",
          onclick: (e) => { e.stopPropagation(); deleteConfig(c); },
        }, "✕")) : null));
    }
  }
}

async function deleteConfig(c) {
  if (!confirm(`¿Borrar la escena «${c.name}»? No se puede deshacer.`)) return;
  try {
    await api("/api/delete-config", { path: c.path });
    if (state.path === c.path) { state.path = null; state.saved = null; renderHeader(); }
    await loadList();
    toast("Escena borrada");
  } catch (e) { toast(e.message, "bad"); }
}

// ------------------------------------------------------------------ abrir / guardar
const isDirty = () => !!state.cfg && JSON.stringify(state.cfg) !== state.saved;

function loadScene(cfg, { path = null, suggestName = null } = {}) {
  state.cfg = cfg;
  state.path = path;
  state.saved = path ? JSON.stringify(cfg) : null;
  state.customRes = false;
  state.suggestName = suggestName;
  delete $("#out-path").dataset.touched;
  stopClip();
  resetHistory();
  document.body.classList.remove("show-list");
  setView("editor");
  renderAll();
}

async function openConfig(path) {
  if (isDirty() && !confirm("Hay cambios sin guardar. ¿Descartarlos?")) return;
  try {
    const cfg = await api("/api/config?path=" + encodeURIComponent(path));
    store.set("vj.last", path);
    loadScene(cfg, { path });
  } catch (e) { toast(e.message, "bad"); }
}

function newScene() {
  if (isDirty() && !confirm("Hay cambios sin guardar. ¿Descartarlos?")) return;
  const output = state.cfg?.output ? clone(state.cfg.output) : {};
  delete output.path;
  loadScene({ output, geometry: { pattern: "organic_waves", params: {} }, palette: { preset: "neon" },
              animation: { speed: 0.25, rotation: 0, wobble: 0.0625, bpm: 0 } }, { suggestName: "nueva" });
}

function importFile(file) {
  const reader = new FileReader();
  reader.onload = () => {
    try {
      const cfg = JSON.parse(reader.result);
      if (typeof cfg !== "object" || Array.isArray(cfg) || !cfg) throw new Error("no es un objeto JSON");
      if (isDirty() && !confirm("Hay cambios sin guardar. ¿Descartarlos?")) return;
      loadScene(cfg, { suggestName: file.name.replace(/\.json$/i, "").replace(/[^A-Za-z0-9_\-]/g, "_") });
      toast(`Importado ${file.name}. Guárdalo para que aparezca en la lista.`, "ok");
    } catch (e) { toast("No se pudo importar: " + e.message, "bad"); }
  };
  reader.readAsText(file);
}

async function save(path = state.path, overwrite = true) {
  try {
    const r = await api("/api/save", { path, config: state.cfg, overwrite });
    state.path = r.path;
    state.saved = JSON.stringify(state.cfg);
    store.set("vj.last", r.path);
    await loadList();
    renderHeader();
    toast("Guardado en " + displayPath(r.path), "ok", null, 2500);
  } catch (e) {
    if (e.status === 409 && confirm("Ya existe una escena con ese nombre. ¿Reemplazarla?")) return save(path, true);
    toast("No se pudo guardar: " + e.message, "bad");
  }
}

function saveShortcut() {
  const info = configInfo(state.path);
  if (state.path && info?.writable) save();
  else openSaveAs();
}

function openSaveAs() {
  const dlg = $("#dlg-saveas");
  const admin = isAdmin();
  $("#saveas-folder-row").hidden = !admin;
  $("#saveas-hint").innerHTML = admin
    ? 'Se guarda en <span class="mono">configs/&lt;carpeta&gt;/&lt;nombre&gt;.json</span>'
    : "Se guarda en <b>mis escenas</b>.";
  const cur = state.path || `mine/${state.suggestName || "nuevo"}.json`;
  const parts = cur.split("/");
  $("#saveas-folder").value = parts.length > 1 && !BUILTIN_GROUPS.includes(parts[0]) && parts[0] !== "users" ? parts[0] : "mine";
  $("#saveas-name").value = parts.at(-1).replace(/\.json$/, "") + (state.path ? "_v2" : "");
  dlg.showModal();
  $("#saveas-name").select();
  dlg.onclose = () => {
    if (dlg.returnValue !== "ok") return;
    const folder = $("#saveas-folder").value.trim().replace(/[^A-Za-z0-9_\-]/g, "");
    const name = $("#saveas-name").value.trim().replace(/[^A-Za-z0-9_\-]/g, "");
    if (name) save(admin && folder ? `${folder}/${name}.json` : `${name}.json`, false);
  };
}

function renderHeader() {
  $("#file-name").textContent = displayPath(state.path);
  $("#dirty").hidden = !isDirty();
  document.title = (isDirty() ? "● " : "") + (state.path ? state.path.split("/").pop().replace(/\.json$/, "") + " — " : "") + "Prism Loops Studio";
}

// ------------------------------------------------------------------ deshacer / rehacer
let histTimer = null;

function resetHistory() {
  clearTimeout(histTimer);
  histTimer = null;
  state.undo = [];
  state.redo = [];
  state.histCur = JSON.stringify(state.cfg);
  renderHistoryButtons();
}

function commitHistory() {
  clearTimeout(histTimer);
  histTimer = null;
  const now = JSON.stringify(state.cfg);
  if (now !== state.histCur) {
    state.undo.push(state.histCur);
    if (state.undo.length > 200) state.undo.shift();
    state.redo = [];
    state.histCur = now;
  }
  renderHistoryButtons();
}

function stepHistory(from, to) {
  if (histTimer) commitHistory();
  if (!from.length) return;
  to.push(state.histCur);
  state.histCur = from.pop();
  state.cfg = JSON.parse(state.histCur);
  renderPanel();
  changed({ record: false });
  renderHistoryButtons();
}
const undo = () => stepHistory(state.undo, state.redo);
const redo = () => stepHistory(state.redo, state.undo);

function renderHistoryButtons() {
  $("#btn-undo").disabled = !state.undo.length && !histTimer;
  $("#btn-redo").disabled = !state.redo.length;
}

// ------------------------------------------------------------------ cambios → previsualización
let previewTimer = null, previewAbort = null, planTimer = null, previewUrl = null;

function changed({ rerender = false, record = true } = {}) {
  renderHeader();
  stopClip();
  if (rerender) renderPanel();
  if (record) { clearTimeout(histTimer); histTimer = setTimeout(commitHistory, 350); renderHistoryButtons(); }
  clearTimeout(previewTimer);
  previewTimer = setTimeout(updatePreview, 220);
  clearTimeout(planTimer);
  planTimer = setTimeout(updatePlan, 220);
  updateOutPath();
}

const previewWidth = () => document.fullscreenElement ? Math.min(1600, screen.width) : state.hq ? 960 : 640;

async function updatePreview() {
  if (!state.cfg) return;
  previewAbort?.abort();
  previewAbort = new AbortController();
  $("#spinner").hidden = false;
  try {
    const blob = await api("/api/preview", { config: state.cfg, phase: state.phase, width: previewWidth(), hq: state.hq },
                           { signal: previewAbort.signal });
    const url = URL.createObjectURL(blob);
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
    const t = document.querySelector(".cycle-timing");
    if (t && state.cfg.palette?.cycle) t.textContent = cycleTiming(state.cfg.palette.cycle);
    renderRenderHint();
    updateOutPath();
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

// ------------------------------------------------------------------ reproducir el loop (vídeo ligero)
async function togglePlay() {
  if (state.playing) return stopClip();
  const btn = $("#btn-play"), video = $("#clip");
  const key = JSON.stringify(state.cfg);
  btn.disabled = true;
  btn.textContent = "… preparando";
  $("#spinner").hidden = false;
  try {
    if (state.clip?.key !== key) {
      const blob = await api("/api/clip", { config: state.cfg, width: 480, fps: 24 });
      if (state.clip) URL.revokeObjectURL(state.clip.url);
      state.clip = { key, url: URL.createObjectURL(blob) };
    }
    if (JSON.stringify(state.cfg) !== key) return;          // cambió mientras se preparaba
    video.src = state.clip.url;
    video.hidden = false;
    await video.play();
    state.playing = true;
    $("#clip-info").hidden = false;
    $("#clip-info").textContent = "vista previa a velocidad real · el render final es más nítido";
  } catch (e) {
    toast("No se pudo reproducir: " + e.message, "bad");
  } finally {
    btn.disabled = false;
    $("#spinner").hidden = true;
    btn.textContent = state.playing ? "■ Detener" : "▶ Reproducir";
  }
}

function stopClip() {
  const video = $("#clip");
  video.pause();
  video.hidden = true;
  $("#clip-info").hidden = true;
  state.playing = false;
  $("#btn-play").textContent = "▶ Reproducir";
}

function toggleFullscreen() {
  const st = $("#stage");
  if (document.fullscreenElement) document.exitFullscreen();
  else (st.requestFullscreen || st.webkitRequestFullscreen)?.call(st);
}

// ------------------------------------------------------------------ controles reutilizables
function slider(label, { get: g, set: s, min, max, step, int = false, dflt, onchange }) {
  const v0 = g();
  const range = el("input", { type: "range", min, max, step, value: v0, "aria-label": label });
  const num = el("input", { type: "number", min, step, value: v0, "aria-label": label });
  const field = el("div", { class: "field" + (dflt !== undefined && v0 !== dflt ? " changed" : "") },
    el("label", {}, el("span", {}, label), dflt !== undefined ? el("span", {
      title: "Doble clic en el control para volver al valor por defecto" }, `def. ${dflt}`) : null),
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
  if (dflt !== undefined) range.addEventListener("dblclick", () => apply(dflt, null));
  return field;
}

function select(label, options, { get: g, set: s, rerender = false }) {
  const sel = el("select", { "aria-label": label }, options.map(([v, t]) =>
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
  changed({ record: false });
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
  if (!spec) return el("p", { class: "hint" }, `Patrón desconocido: ${pattern}`);
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
    const duplicate = () => { cfg.layers.splice(i + 1, 0, clone(layer)); changed({ rerender: true }); };
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
        el("button", { class: "small ghost", title: "Duplicar", onclick: duplicate }, "⧉"),
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
      const inp = el("input", { type: "color", value: c, "aria-label": `Color ${i + 1}` });
      inp.addEventListener("input", () => { p.colors[i] = inp.value; changed(); grad.style.background = gradientCss(p.colors); });
      sw.append(el("span", { class: "swatch" }, inp, p.colors.length > 1 ? el("button", {
        class: "small ghost", title: "Quitar", onclick: () => { p.colors.splice(i, 1); changed({ rerender: true }); },
      }, "✕") : null));
    });
    if (p.colors.length < 8) sw.append(el("button", { class: "small", onclick: () => {
      p.colors.push(p.colors.at(-1)); changed({ rerender: true });
    } }, "+ color"));
    const grad = el("div", { class: "gradient", style: `background:${gradientCss(p.colors)}` });
    panel.append(el("p", { class: "hint" }, "Gradiente cíclico: el último color enlaza con el primero."), sw, grad,
      el("button", { class: "small", style: "margin-bottom:12px", onclick: () => {
        p.colors.reverse(); changed({ rerender: true });
      } }, "⇄ Invertir orden"));
  }

  const bgDefault = presets[p.preset]?.background || "#000000";
  const bg = el("input", { type: "color", value: p.background || bgDefault, "aria-label": "Fondo" });
  bg.addEventListener("input", () => { p.background = bg.value; changed(); });
  panel.append(
    el("div", { class: "field" }, el("label", {}, "Fondo"), el("div", { class: "row" }, bg,
      el("button", { class: "small ghost", onclick: () => { delete p.background; changed({ rerender: true }); } }, "por defecto"))),
    slider("Intensidad", { get: () => p.intensity ?? 1, set: (v) => { p.intensity = v; },
                           min: 0, max: 3, step: 0.01, dflt: 1 }),
  );
  colorCycleSection(panel, p);
}

// ---- Cambio de colores durante el loop (palette.cycle)
function hexToHsl(hex) {
  const n = parseInt(hex.slice(1), 16), r = (n >> 16) / 255, g = ((n >> 8) & 255) / 255, b = (n & 255) / 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b), l = (max + min) / 2, d = max - min;
  if (!d) return [0, 0, l];
  const s = d / (1 - Math.abs(2 * l - 1));
  const h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [(h * 60 + 360) % 360, s, l];
}
function hslToHex(h, s, l) {
  const c = (1 - Math.abs(2 * l - 1)) * s, x = c * (1 - Math.abs((h / 60) % 2 - 1)), m = l - c / 2;
  const [r, g, b] = h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x] : h < 240 ? [0, x, c] : h < 300 ? [x, 0, c] : [c, 0, x];
  return "#" + [r, g, b].map((v) => Math.round((v + m) * 255).toString(16).padStart(2, "0")).join("");
}
const rotateHue = (hex, deg) => { const [h, s, l] = hexToHsl(hex); return hslToHex((h + deg + 360) % 360, s, l); };

const paletteColors = (pal) => pal.colors || state.meta.presets[pal.preset]?.colors || ["#ffffff"];
const paletteBg = (pal) => pal.background || state.meta.presets[pal.preset]?.background || "#000000";

function cycleTiming(cyc) {
  const changes = (cyc.repeats ?? 1) * (cyc.palettes.length + 1);
  const p = state.plan;
  if (!p) return "";
  let txt = `${changes} cambios por loop · cada ${(p.duration / changes).toFixed(2)} s`;
  const beats = p.cycles.beats;
  if (beats && beats % changes === 0) {
    const per = beats / changes, bpb = val("animation.beats_per_bar");
    txt += per % bpb === 0 ? ` (${per / bpb} ${per / bpb > 1 ? "compases" : "compás"})` : ` (${per} golpes)`;
  } else if (beats) txt += " · no cae en los golpes: ajusta las vueltas o el número de paletas";
  return txt;
}

function colorCycleSection(panel, p) {
  const on = !!p.cycle?.palettes?.length;
  const box = el("div", { class: "cycle" });
  box.append(el("h4", {}, "Cambio de colores en el loop"),
    el("label", { class: "toggle" }, el("input", { type: "checkbox", checked: on, onchange: (e) => {
      if (e.target.checked) {
        const base = paletteColors(p);
        p.cycle = { palettes: [{ colors: base.map((c) => rotateHue(c, 120)), background: rotateHue(paletteBg(p), 120) },
                               { colors: base.map((c) => rotateHue(c, 240)), background: rotateHue(paletteBg(p), 240) }],
                    repeats: 1, transition: 0.35 };
      } else delete p.cycle;
      changed({ rerender: true });
    } }), "La paleta va cambiando a lo largo del loop"));
  panel.append(box);
  if (!on) {
    box.append(el("p", { class: "hint" }, "Define una secuencia de paletas: el loop pasa de una a otra y la última enlaza con la primera, sin salto."));
    return;
  }
  const cyc = p.cycle;
  cyc.repeats ??= 1;
  cyc.transition ??= 0.35;
  const timing = el("p", { class: "hint tight cycle-timing" }, cycleTiming(cyc));
  const seq = el("div", { class: "cycle-seq" });
  const strip = (cols, bg) => el("div", { class: "g", style: `background:${gradientCss(cols)};box-shadow:inset 0 0 0 3px ${bg}` });
  seq.append(el("div", { class: "cycle-item base" }, el("b", {}, "1 · base"), strip(paletteColors(p), paletteBg(p)),
    el("small", { class: "hint" }, "la de arriba")));

  cyc.palettes.forEach((pal, i) => {
    const presetNames = Object.keys(state.meta.presets);
    const custom = Array.isArray(pal.colors);
    const move = (d) => {
      const j = i + d;
      if (j < 0 || j >= cyc.palettes.length) return;
      [cyc.palettes[i], cyc.palettes[j]] = [cyc.palettes[j], cyc.palettes[i]];
      changed({ rerender: true });
    };
    const kind = el("select", { "aria-label": `Paleta ${i + 2}` },
      el("option", { value: "__custom", selected: custom }, "Personalizada"),
      presetNames.map((n) => el("option", { value: n, selected: !custom && pal.preset === n }, n.replaceAll("_", " "))));
    kind.addEventListener("change", () => {
      if (kind.value === "__custom") { pal.colors = [...paletteColors(pal)]; pal.background = paletteBg(pal); delete pal.preset; }
      else { pal.preset = kind.value; delete pal.colors; delete pal.background; }
      changed({ rerender: true });
    });
    const item = el("div", { class: "cycle-item" },
      el("div", { class: "card-head" }, el("b", {}, `${i + 2}`), kind,
        el("button", { class: "small ghost", title: "Antes", onclick: () => move(-1) }, "↑"),
        el("button", { class: "small ghost", title: "Después", onclick: () => move(1) }, "↓"),
        el("button", { class: "small ghost", title: "Duplicar", onclick: () => { cyc.palettes.splice(i + 1, 0, clone(pal)); changed({ rerender: true }); } }, "⧉"),
        el("button", { class: "small ghost danger", title: "Quitar", onclick: () => {
          cyc.palettes.splice(i, 1);
          if (!cyc.palettes.length) delete p.cycle;
          changed({ rerender: true });
        } }, "✕")));
    if (custom) {
      const sw = el("div", { class: "swatches" });
      pal.colors.forEach((c, k) => {
        const inp = el("input", { type: "color", value: c, "aria-label": `Paleta ${i + 2}, color ${k + 1}` });
        inp.addEventListener("input", () => { pal.colors[k] = inp.value; changed(); });
        inp.addEventListener("change", () => renderPanel());
        sw.append(el("span", { class: "swatch" }, inp, pal.colors.length > 1 ? el("button", {
          class: "small ghost", title: "Quitar color", onclick: () => { pal.colors.splice(k, 1); changed({ rerender: true }); },
        }, "✕") : null));
      });
      if (pal.colors.length < 8) sw.append(el("button", { class: "small", onclick: () => { pal.colors.push(pal.colors.at(-1)); changed({ rerender: true }); } }, "+"));
      const bg = el("input", { type: "color", value: paletteBg(pal), "aria-label": `Paleta ${i + 2}, fondo`, title: "Fondo" });
      bg.addEventListener("input", () => { pal.background = bg.value; changed(); });
      item.append(sw, el("label", { class: "toggle" }, bg, "fondo"));
    }
    item.append(strip(paletteColors(pal), paletteBg(pal)));
    seq.append(item);
  });
  box.append(seq, el("div", { class: "row", style: "display:flex;gap:6px;flex-wrap:wrap;margin:8px 0 12px" },
    el("button", { class: "small", onclick: () => {
      const last = cyc.palettes.at(-1) || p;
      cyc.palettes.push({ colors: paletteColors(last).map((c) => rotateHue(c, 60)), background: rotateHue(paletteBg(last), 60) });
      changed({ rerender: true });
    } }, "+ Añadir paleta"),
    el("button", { class: "small ghost", title: "Reemplaza la secuencia por la base girada en el círculo cromático", onclick: () => {
      const n = cyc.palettes.length + 1, base = paletteColors(p);
      cyc.palettes = Array.from({ length: n - 1 }, (_, k) => ({
        colors: base.map((c) => rotateHue(c, (360 * (k + 1)) / n)), background: rotateHue(paletteBg(p), (360 * (k + 1)) / n) }));
      changed({ rerender: true });
    } }, "✦ Girar tonos de la base"),
    el("button", { class: "small ghost", title: "Paletas al azar entre los presets", onclick: () => {
      const names = Object.keys(state.meta.presets).filter((n) => n !== p.preset).sort(() => Math.random() - 0.5);
      cyc.palettes = cyc.palettes.map((_, k) => ({ preset: names[k % names.length] }));
      changed({ rerender: true });
    } }, "🎲 Presets al azar")));
  box.append(
    slider("Vueltas de la secuencia por loop", { get: () => cyc.repeats, set: (v) => { cyc.repeats = Math.max(1, v); timing.textContent = cycleTiming(cyc); },
                                                  min: 1, max: 16, step: 1, int: true, dflt: 1 }),
    slider("Transición (0 = corte seco, 1 = fundido continuo)", { get: () => cyc.transition, set: (v) => { cyc.transition = v; },
                                                                   min: 0, max: 1, step: 0.05, dflt: 0.35 }),
    timing);
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
function limitsText() {
  const l = limits();
  if (!l) return "";
  const px = l.max_pixels;
  const name = px >= 3840 * 2160 ? "4K" : px >= 2560 * 1440 ? "1440p" : px >= 1920 * 1080 ? "1080p" : "720p";
  return `Límites de este servidor: hasta ${name}, loops de ${l.max_duration} s, ${l.max_fps} fps, ${l.max_jobs} renders a la vez.`;
}

function tabOutput(panel) {
  const m = state.meta, w = val("output.width"), h = val("output.height");
  const grid = el("div", { class: "export-grid" });
  for (const ex of m.export_presets) {
    const o = ex.output;
    const on = o.width === w && o.height === h && o.fps === val("output.fps") && o.codec === val("output.codec")
      && o.quality === val("output.quality");
    grid.append(el("button", { class: on ? "on" : "", title: ex.desc, onclick: () => {
      for (const [k, v] of Object.entries(o)) set(state.cfg, "output." + k, clone(v));
      if (!o.motion_blur && val("output.motion_blur.samples") > 1) set(state.cfg, "output.motion_blur.samples", 1);
      state.customRes = false;
      changed({ rerender: true });
    } }, ex.label, el("small", {}, ex.desc)));
  }
  panel.append(el("p", { class: "hint tight", style: "margin-bottom:8px" }, "Destino"), grid);
  if (limits()) panel.append(el("p", { class: "hint limits" }, limitsText()));

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
  else panel.append(slider("Duración del loop (s)", { ...bindPath("output.duration"), min: 1, max: 120, step: 0.5 }));
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
    el("p", { class: "hint" }, "Supersampling y motion blur multiplican el tiempo de render; la vista previa los omite salvo con «Calidad final». " +
      "Para vídeos de 1 hora renderiza un loop corto y usa «Versión larga» en la galería."),
  );
}

// ---- Post
function tabPost(panel) {
  for (const f of state.meta.sections.post) {
    panel.append(slider(f.label, { ...bindPath("post." + f.key), min: f.min, max: f.max, step: f.step,
                                   dflt: get(D(), "post." + f.key) }));
  }
  panel.append(el("button", { class: "small ghost", onclick: () => { delete state.cfg.post; changed({ rerender: true }); } },
    "Restablecer post-proceso"));
}

// ---- JSON
function tabJson(panel) {
  const ta = el("textarea", { id: "json-area", spellcheck: "false" }, JSON.stringify(state.cfg, null, 2));
  const fileName = () => sceneName() + ".json";
  panel.append(ta, el("div", { class: "row", style: "margin-top:8px;display:flex;gap:8px;flex-wrap:wrap" },
    el("button", { onclick: () => {
      try {
        const cfg = JSON.parse(ta.value);
        if (typeof cfg !== "object" || Array.isArray(cfg) || !cfg) throw new Error("debe ser un objeto");
        state.cfg = cfg; changed(); toast("JSON aplicado", "ok", null, 1500);
      } catch (e) { toast("JSON inválido: " + e.message, "bad"); }
    } }, "Aplicar"),
    el("button", { class: "ghost", onclick: () => {
      const a = el("a", { href: URL.createObjectURL(new Blob([JSON.stringify(state.cfg, null, 2) + "\n"], { type: "application/json" })),
                          download: fileName() });
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    } }, "⬇ Descargar .json"),
    el("button", { class: "ghost", onclick: async () => {
      try { await navigator.clipboard.writeText(JSON.stringify(state.cfg, null, 2)); toast("Copiado", "ok", null, 1500); }
      catch { ta.select(); document.execCommand("copy"); }
    } }, "Copiar")));
}

// ------------------------------------------------------------------ renders
function sceneName() {
  return (state.path || state.suggestName || "loop").split("/").pop().replace(/\.json$/, "");
}

function updateOutPath() {
  const inp = $("#out-path");
  if (inp.dataset.touched) return;
  if (!isAdmin()) { inp.value = sceneName(); return; }
  inp.value = state.cfg?.output?.path && !state.cfg.output.path.startsWith("renders/loop")
    ? state.cfg.output.path.replace(/\.(mp4|mov)$/, "") + (state.plan?.container || ".mp4")
    : `renders/${sceneName()}${state.plan?.container || ".mp4"}`;
}

function renderRenderHint() {
  const p = state.plan;
  const parts = [];
  if (p) parts.push(`${val("output.width")}×${val("output.height")} · ${p.frames} frames · loop de ${p.duration.toFixed(1)} s`);
  if (!isAdmin()) parts.push("se guarda en tu galería");
  const l = limits(), hint = $("#render-hint");
  const over = l && p && (val("output.width") * val("output.height") > l.max_pixels || p.duration > l.max_duration + 1e-6
                          || val("output.fps") > l.max_fps);
  if (over) parts.unshift("⚠ Esta escena supera los límites del servidor: en Salida elige un destino como «YouTube 1080p60» o «Borrador rápido»");
  else if (l) parts.push(limitsText());
  hint.textContent = parts.join(" · ");
  hint.classList.toggle("warn", !!over);
}

async function startRender() {
  const btn = $("#btn-render");
  btn.disabled = true;
  try {
    if ("Notification" in window && Notification.permission === "default") Notification.requestPermission().catch(() => {});
    await api("/api/render", { config: state.cfg, output: $("#out-path").value, name: sceneName() });
    toast("Render en cola", "ok", null, 2000);
    pollJobs(true);
  } catch (e) { toast("No se pudo iniciar el render: " + e.message, "bad", null, 8000); }
  finally { btn.disabled = false; }
}

const fmtTime = (s) => s == null ? "—" : s >= 3600 ? `${(s / 3600).toFixed(1)} h` : s >= 60 ? `${Math.floor(s / 60)} min ${Math.round(s % 60)} s` : `${Math.round(s)} s`;
const fmtSize = (b) => b >= 1e9 ? `${(b / 1e9).toFixed(2)} GB` : b >= 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${Math.round(b / 1e3)} KB`;
const ACTIVE = ["en cola", "renderizando", "cancelando"];

let jobsTimer = null;
async function pollJobs(soon = false) {
  clearTimeout(jobsTimer);
  let jobs = state.jobs;
  try { jobs = await api("/api/jobs"); } catch { /* servidor ocupado: reintenta */ }
  notifyTransitions(jobs);
  state.jobs = jobs;
  renderJobs();
  const active = jobs.some((j) => ACTIVE.includes(j.state));
  jobsTimer = setTimeout(pollJobs, active || soon ? 1000 : 5000);
}

function notifyTransitions(jobs) {
  let refresh = false;
  for (const j of jobs) {
    const prev = state.jobStates[j.id];
    state.jobStates[j.id] = j.state;
    if (!prev || prev === j.state || !ACTIVE.includes(prev)) continue;
    if (j.state === "listo") {
      refresh = true;
      const what = j.kind === "extend" ? "Versión larga lista" : "Render listo";
      toast(`✓ ${what}: ${j.name}`, "ok", j.media ? { label: "Ver", fn: () => openPlayerByPath(j.media) } : null, 0);
      if ("Notification" in window && Notification.permission === "granted" && document.hidden) {
        try { new Notification(`Prism Loops: ${what.toLowerCase()}`, { body: j.name }); } catch { /* sin permiso */ }
      }
    } else if (j.state === "error") {
      toast(`✗ Falló: ${j.name}`, "bad", null, 0);
    }
  }
  if (refresh) loadRenders();
}

function renderJobs() {
  const jobs = state.jobs;
  const active = jobs.filter((j) => ACTIVE.includes(j.state));
  const pill = $("#queue-pill");
  const running = active.find((j) => j.state === "renderizando");
  pill.hidden = !active.length;
  if (running) {
    const pct = running.total ? Math.round(100 * running.frame / running.total) : 0;
    pill.textContent = `⟳ ${running.name} ${pct}%` + (active.length > 1 ? ` · ${active.length - 1} en cola` : "");
  } else pill.textContent = `${active.length} en cola`;

  const box = $("#jobs");
  box.replaceChildren();
  const done = jobs.filter((j) => !ACTIVE.includes(j.state)).reverse();
  const shown = [...active.reverse(), ...done.slice(0, 4)];
  for (const j of shown) box.append(jobRow(j));
  if (done.length > 4) {
    box.append(el("div", { class: "jobs-more" }, `y ${done.length - 4} trabajos anteriores · `,
      el("button", { class: "small ghost", onclick: () => setView("gallery") }, "ver la galería")));
  }
}

function jobRow(j) {
  const pct = j.total ? (100 * j.frame / j.total) : (j.state === "listo" ? 100 : 0);
  const elapsed = j.started ? ((j.finished || Date.now() / 1000) - j.started) : null;
  const actions = [];
  if (["en cola", "renderizando"].includes(j.state))
    actions.push(el("button", { class: "small ghost danger", onclick: () => api("/api/cancel", { id: j.id }).then(() => pollJobs(true)).catch((e) => toast(e.message, "bad")) }, "Cancelar"));
  if (j.state === "listo" && j.media) {
    actions.push(el("button", { class: "small", onclick: () => openPlayerByPath(j.media) }, "▶ Ver"));
    actions.push(el("a", { class: "btn small", href: `/media/${encPath(j.media)}?dl=1`, download: "", title: "Descargar" }, "⬇"));
    if (state.me.can_reveal)
      actions.push(el("button", { class: "small ghost", title: "Mostrar en Finder", onclick: () => api("/api/reveal", { path: j.output }).catch((e) => toast(e.message, "bad")) }, "Finder"));
  }
  if (!ACTIVE.includes(j.state))
    actions.push(el("button", { class: "small ghost", title: "Quitar de la lista (no borra el vídeo)", onclick: () => api("/api/forget", { id: j.id }).then(() => pollJobs(true)) }, "✕"));
  const progress = j.kind === "extend"
    ? (j.total ? `${fmtTime(j.frame)} de ${fmtTime(j.total)}` : "")
    : (j.total ? `frame ${j.frame}/${j.total}` : "");
  return el("div", { class: "job" },
    el("div", { class: "job-head" }, el("span", { class: "name" }, (j.kind === "extend" ? "⟳ " : "") + j.name),
      isAdmin() && state.me.shared && j.owner !== "local" ? el("span", { class: "badge" }, j.owner) : null,
      el("span", { class: "badge " + j.state }, j.state), el("span", { class: "actions-inline" }, ...actions)),
    el("div", { class: "bar" }, el("div", { style: `width:${pct.toFixed(1)}%` })),
    el("div", { class: "job-meta" },
      el("span", {}, progress),
      el("span", {}, j.fps && j.kind === "render" ? `${j.fps.toFixed(1)} fps` : ""),
      el("span", {}, j.state === "renderizando" ? `quedan ${fmtTime(j.eta)}` : elapsed && j.state === "listo" ? `tardó ${fmtTime(elapsed)}` : ""),
      el("span", {}, j.encoder), el("span", { class: "mono" }, j.output.split(/[\\/]/).slice(-2).join("/"))),
    j.state === "error" ? el("pre", {}, j.log.join("\n")) : null,
  );
}

// ------------------------------------------------------------------ galería
function setView(view) {
  state.view = view;
  for (const b of document.querySelectorAll(".views button")) b.classList.toggle("on", b.dataset.view === view);
  $("#view-editor").hidden = view !== "editor";
  $("#view-gallery").hidden = view !== "gallery";
  if (view === "gallery") loadRenders();
}

async function loadRenders() {
  try { state.renders = await api("/api/renders"); } catch { return; }
  $("#gallery-count").textContent = state.renders.length || "";
  if (state.view === "gallery") renderGallery();
}

function renderGallery() {
  const q = $("#gallery-search").value.trim().toLowerCase();
  const box = $("#gallery");
  box.replaceChildren();
  const items = state.renders.filter((r) => !q || `${r.name} ${r.owner}`.toLowerCase().includes(q));
  if (!items.length) {
    box.append(el("div", { class: "empty" }, state.renders.length ? "Nada coincide."
      : "Aún no hay vídeos. Renderiza una escena desde el Editor y aparecerá aquí."));
    return;
  }
  for (const r of items) {
    const date = new Date(r.mtime * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
    box.append(el("button", { class: "vid", onclick: () => openPlayer(r) },
      el("div", { class: "poster" },
        el("img", { loading: "lazy", alt: "", src: `/api/thumb?render=${encodeURIComponent(r.path)}&v=${r.mtime}`,
                    style: "width:100%;height:100%;object-fit:cover;display:block",
                    onerror: (e) => { e.target.style.visibility = "hidden"; } }),
        r.minutes ? el("span", { class: "long" }, r.minutes >= 60 ? `${r.minutes / 60} h` : `${r.minutes} min`) : null,
        el("span", {}, fmtSize(r.size))),
      el("div", { class: "info" }, el("b", {}, r.name),
        el("small", {}, date + (isAdmin() && state.me.shared && r.owner !== "local" ? ` · ${r.owner}` : "")))));
  }
}

function openPlayerByPath(path) {
  const r = state.renders.find((x) => x.path === path);
  if (r) return openPlayer(r);
  loadRenders().then(() => {
    const r2 = state.renders.find((x) => x.path === path);
    if (r2) openPlayer(r2); else toast("No encuentro ese vídeo", "bad");
  });
}

let playerItem = null;
function openPlayer(r) {
  playerItem = r;
  const dlg = $("#dlg-player"), video = $("#player");
  $("#player-title").textContent = r.name;
  $("#player-note").textContent = "";
  video.onerror = () => {
    if (!dlg.open) return;
    $("#player-note").textContent = "Este navegador no puede reproducir el vídeo aquí (ProRes y HEVC suelen necesitar Safari). Descárgalo para verlo.";
  };
  video.onloadedmetadata = () => renderPlayerMeta(r, video.duration);
  video.src = `/media/${encPath(r.path)}`;
  renderPlayerMeta(r, null);
  $("#player-dl").href = `/media/${encPath(r.path)}?dl=1`;
  $("#player-dl").setAttribute("download", r.name);
  $("#player-open").hidden = !r.has_config;
  $("#player-reveal").hidden = !state.me.can_reveal;
  dlg.showModal();
  video.play().catch(() => {});
}

function renderPlayerMeta(r, duration) {
  const date = new Date(r.mtime * 1000).toLocaleString();
  $("#player-meta").replaceChildren(...[
    el("span", {}, fmtSize(r.size)), el("span", {}, date),
    duration ? el("span", {}, `duración ${fmtTime(duration)}`) : null,
    isAdmin() && state.me.shared ? el("span", {}, `de ${r.owner}`) : null,
    el("span", { class: "mono" }, r.path)].filter(Boolean));
}

// ------------------------------------------------------------------ variaciones y escenas al azar
let varyMode = "vary";
function openVary(mode) {
  varyMode = mode;
  $("#vary-title").textContent = mode === "surprise" ? "🎲 Escenas nuevas al azar" : "✦ Variaciones de esta escena";
  $("#vary-controls").hidden = mode === "surprise";
  $("#dlg-vary").showModal();
  generateVariations();
}

let varyAbort = null;
async function generateVariations() {
  const grid = $("#vary-grid");
  grid.replaceChildren(el("div", { class: "loading" }, "Generando…"));
  varyAbort?.abort();
  varyAbort = new AbortController();
  try {
    const r = await api("/api/variations", {
      mode: varyMode, config: state.cfg || {}, amount: Number($("#vary-amount").value), count: 6, width: 360,
    }, { signal: varyAbort.signal });
    grid.replaceChildren();
    r.items.forEach((it, i) => {
      const desc = (it.config.layers || [it.config.geometry]).map((l) => l.pattern.replaceAll("_", " ")).join(" + ");
      grid.append(el("button", { title: "Usar esta", onclick: () => pickVariation(it.config) },
        it.image ? el("img", { src: it.image, alt: `Opción ${i + 1}` }) : el("span", { class: "hint" }, "sin imagen"),
        el("small", {}, desc)));
    });
  } catch (e) {
    if (e.name !== "AbortError") grid.replaceChildren(el("div", { class: "loading" }, "Error: " + e.message));
  }
}

function pickVariation(cfg) {
  $("#dlg-vary").close();
  if (varyMode === "surprise") {
    if (isDirty() && !confirm("Hay cambios sin guardar. ¿Descartarlos?")) return;
    loadScene(cfg, { suggestName: "aleatoria" });
    toast("Escena nueva. Guárdala si te gusta (⌘S).", "ok");
    return;
  }
  if (histTimer) commitHistory();
  state.cfg = cfg;
  renderPanel();
  changed();
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

// ------------------------------------------------------------------ atajos
const inControl = (t) => t.closest("input, textarea, select, button, a, [contenteditable], dialog");

function onKey(e) {
  const mod = e.metaKey || e.ctrlKey;
  if (mod && e.key.toLowerCase() === "s") { e.preventDefault(); return saveShortcut(); }
  const typing = e.target.closest("textarea, input[type=text], input[type=number], input[type=search], input:not([type])");
  if (mod && !typing && e.key.toLowerCase() === "z") { e.preventDefault(); return e.shiftKey ? redo() : undo(); }
  if (mod && !typing && e.key.toLowerCase() === "y") { e.preventDefault(); return redo(); }
  if (mod || e.altKey || inControl(e.target) || state.view !== "editor" || !state.cfg) return;
  if (e.key === " ") { e.preventDefault(); togglePlay(); }
  else if (e.key === "f" || e.key === "F") toggleFullscreen();
  else if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
    e.preventDefault();
    const step = e.shiftKey ? 0.1 : 0.01;
    state.phase = (state.phase + (e.key === "ArrowRight" ? step : -step) + 1) % 1;
    $("#phase").value = state.phase;
    onPhase();
  }
}

function onPhase() {
  updatePhaseLabel();
  stopClip();
  clearTimeout(previewTimer);
  previewTimer = setTimeout(updatePreview, 60);
}

// ------------------------------------------------------------------ compartir
function openShare() {
  const box = $("#share-body"), sh = state.me.share;
  box.replaceChildren();
  if (!sh) {
    box.append(
      el("p", {}, "Ahora mismo el estudio solo es accesible desde este equipo."),
      el("p", { class: "hint" }, "Para que otras personas de tu red (Wi-Fi) lo usen desde su navegador, cierra esta ventana y abre " +
        "«Prism Loops Studio (compartir)», o ejecuta:"),
      el("pre", { class: "code" }, "python -m vj.gui --share"),
      el("p", { class: "hint" }, "Cada persona entra con su nombre y un código de acceso; sus escenas y vídeos quedan separados " +
        "de los tuyos y hay límites de resolución y duración configurables. Para acceso desde Internet, mira «Compartir» en el README."));
    return $("#dlg-share").showModal();
  }
  const invite = `Entra en Prism Loops Studio:\n${sh.urls[0]}\nCódigo de acceso: ${sh.code}`;
  box.append(
    el("p", { class: "hint" }, "Las personas conectadas a tu misma red pueden entrar con:"),
    ...sh.urls.map((u) => el("div", { class: "share-url mono" }, el("a", { href: u, target: "_blank" }, u))),
    el("p", { class: "hint" }, "Código de acceso:"),
    el("div", { class: "share-code mono" }, sh.code),
    el("menu", {}, el("button", { onclick: async () => {
      try { await navigator.clipboard.writeText(invite); toast("Invitación copiada", "ok", null, 1500); }
      catch { prompt("Copia la invitación:", invite); }
    } }, "Copiar invitación")),
    el("p", { class: "hint" }, "Tú (en este equipo) no necesitas código y ves los trabajos de todos."));
  $("#dlg-share").showModal();
}

// ------------------------------------------------------------------ arranque
async function init() {
  $("#login-form").addEventListener("submit", doLogin);
  state.me = await api("/api/me");
  if (!state.me.user) return showLogin();

  state.meta = await api("/api/meta");
  $("#gpu").textContent = state.meta.gpu_error ? "Sin GPU: " + state.meta.gpu_error : "GPU: " + state.meta.gpu;
  if (state.me.shared) {
    $("#user-chip").hidden = false;
    $("#user-name").textContent = state.me.user.name + (state.me.user.admin ? " (admin)" : "");
    $("#btn-logout").hidden = state.me.user.name === "local";
  }
  $("#btn-share").hidden = !state.me.can_reveal;
  bindUi();
  await loadList();
  const last = store.get("vj.last");
  const first = state.configs.find((c) => c.path === last) || state.configs.find((c) => c.group === "showcase") || state.configs[0];
  if (first) await openConfig(first.path);
  else newScene();
  pollJobs();
  loadRenders();
}

function bindUi() {
  $("#search").addEventListener("input", renderList);
  $("#tabs").addEventListener("click", (e) => {
    const t = e.target.closest("button");
    if (t) { state.tab = t.dataset.tab; renderPanel(); }
  });
  document.querySelector(".views").addEventListener("click", (e) => {
    const t = e.target.closest("button[data-view]");
    if (t) setView(t.dataset.view);
  });
  $("#queue-pill").addEventListener("click", () => { setView("editor"); $("#jobs").scrollIntoView({ behavior: "smooth" }); });
  $("#phase").addEventListener("input", (e) => { state.phase = Number(e.target.value); onPhase(); });
  $("#hq").addEventListener("change", (e) => { state.hq = e.target.checked; updatePreview(); });
  $("#btn-play").addEventListener("click", togglePlay);
  $("#btn-full").addEventListener("click", toggleFullscreen);
  document.addEventListener("fullscreenchange", updatePreview);
  $("#btn-check").addEventListener("click", checkLoop);
  $("#btn-vary").addEventListener("click", () => openVary("vary"));
  $("#btn-surprise").addEventListener("click", () => openVary("surprise"));
  $("#btn-vary-again").addEventListener("click", generateVariations);
  $("#vary-amount").addEventListener("change", generateVariations);
  $("#btn-render").addEventListener("click", startRender);
  $("#out-path").addEventListener("input", (e) => { e.target.dataset.touched = "1"; });
  $("#btn-save").addEventListener("click", saveShortcut);
  $("#btn-saveas").addEventListener("click", openSaveAs);
  $("#btn-revert").addEventListener("click", () => {
    if (!state.saved) return;
    if (histTimer) commitHistory();
    state.cfg = JSON.parse(state.saved);
    renderPanel();
    changed();
  });
  $("#btn-share").addEventListener("click", openShare);
  $("#btn-undo").addEventListener("click", undo);
  $("#btn-redo").addEventListener("click", redo);
  $("#btn-new").addEventListener("click", newScene);
  $("#btn-import").addEventListener("click", () => $("#import-file").click());
  $("#import-file").addEventListener("change", (e) => { if (e.target.files[0]) importFile(e.target.files[0]); e.target.value = ""; });
  $("#btn-menu").addEventListener("click", () => document.body.classList.toggle("show-list"));
  $("#btn-logout").addEventListener("click", async () => { await api("/api/logout", {}); location.reload(); });
  $("#gallery-search").addEventListener("input", renderGallery);
  $("#btn-gallery-refresh").addEventListener("click", loadRenders);

  // Arrastrar un .json a la ventana lo importa.
  document.addEventListener("dragover", (e) => { if ([...e.dataTransfer.types].includes("Files")) e.preventDefault(); });
  document.addEventListener("drop", (e) => {
    const f = e.dataTransfer.files[0];
    if (f && /\.json$/i.test(f.name)) { e.preventDefault(); importFile(f); }
  });

  // Diálogos: botón ✕ y vídeo que deja de sonar/descargar al cerrar.
  for (const b of document.querySelectorAll("[data-close]")) b.addEventListener("click", () => b.closest("dialog").close());
  $("#dlg-player").addEventListener("close", () => { const v = $("#player"); v.pause(); v.removeAttribute("src"); v.load(); });
  $("#dlg-vary").addEventListener("close", () => varyAbort?.abort());
  $("#player-open").addEventListener("click", async () => {
    try {
      const cfg = await api("/api/render-config?path=" + encodeURIComponent(playerItem.path));
      if (isDirty() && !confirm("Hay cambios sin guardar. ¿Descartarlos?")) return;
      $("#dlg-player").close();
      loadScene(cfg, { suggestName: playerItem.name.replace(/\.[^.]+$/, "") });
    } catch (e) { toast(e.message, "bad"); }
  });
  $("#player-reveal").addEventListener("click", () => api("/api/reveal", { path: "renders/" + playerItem.path }).catch((e) => toast(e.message, "bad")));
  $("#player-delete").addEventListener("click", async () => {
    if (!confirm(`¿Borrar «${playerItem.name}» del disco? No se puede deshacer.`)) return;
    try {
      await api("/api/delete-render", { path: playerItem.path });
      $("#dlg-player").close();
      toast("Vídeo borrado");
      loadRenders();
    } catch (e) { toast(e.message, "bad"); }
  });
  $("#btn-extend").addEventListener("click", async () => {
    const minutes = Number($("#extend-min").value);
    try {
      await api("/api/extend", { path: playerItem.path, minutes });
      $("#dlg-player").close();
      toast(`Creando la versión de ${minutes >= 60 ? minutes / 60 + " h" : minutes + " min"}… aparecerá en la galería`, "ok");
      setView("editor");
      pollJobs(true);
    } catch (e) { toast(e.message, "bad"); }
  });

  document.addEventListener("keydown", onKey);
  window.addEventListener("beforeunload", (e) => { if (isDirty()) e.preventDefault(); });
}

init().catch((e) => { banner("No se pudo iniciar la interfaz: " + e.message); console.error(e); });
