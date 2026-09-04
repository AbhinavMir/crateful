const HELPER = "http://127.0.0.1:7531";
const $ = (id) => document.getElementById(id);

let defaultPrompt = "";
let supportedProviders = ["anthropic", "openai"];
let defaultModels = { anthropic: "claude-sonnet-4-6", openai: "gpt-4o" };
let currentProvider = "anthropic";

function setStatus(el, kind, text) {
  el.className = el.dataset.baseClass || el.className.split(" ")[0];
  el.classList.add(kind);
  el.textContent = text;
}

async function load() {
  const status = $("status");
  status.dataset.baseClass = "status";
  try {
    const res = await fetch(`${HELPER}/config`);
    if (!res.ok) throw new Error(await res.text());
    const cfg = await res.json();

    defaultPrompt = cfg.default_prompt || "";
    supportedProviders = cfg.supported_providers || supportedProviders;
    defaultModels = cfg.default_models || defaultModels;
    currentProvider = cfg.provider;

    $("audio-root").value = cfg.audio_root || "";
    $("video-root").value = cfg.video_root || "";
    $("model").value = cfg.model || "";
    $("ollama-url").value = cfg.ollama_url || "";
    fillCookieBrowsers(cfg.supported_cookie_browsers || [], cfg.cookies_from_browser || "");

    renderProviderRadios(cfg.provider);
    updateModelHint();
    updateProviderVisibility();

    $("anthropic-key").value = "";
    $("openai-key").value = "";
    $("anthropic-key-status").textContent = cfg.has_anthropic_key ? "Key configured." : "No key set.";
    $("anthropic-key-status").className = "muted " + (cfg.has_anthropic_key ? "ok" : "");
    $("openai-key-status").textContent = cfg.has_openai_key ? "Key configured." : "No key set.";
    $("openai-key-status").className = "muted " + (cfg.has_openai_key ? "ok" : "");

    const promptValue = cfg.categorize_prompt && cfg.categorize_prompt.trim() ? cfg.categorize_prompt : defaultPrompt;
    $("prompt").value = promptValue;
    $("prompt-status").textContent = cfg.active_prompt_is_default ? "Using default prompt." : "Custom prompt active.";

    status.className = "status ok";
    status.textContent = "Loaded.";
  } catch (e) {
    status.className = "status err";
    status.textContent = `Couldn't load config: ${e.message || e}`;
  }
}

function renderProviderRadios(active) {
  const wrap = $("provider-radios");
  wrap.innerHTML = "";
  for (const p of supportedProviders) {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "provider";
    input.value = p;
    if (p === active) input.checked = true;
    input.addEventListener("change", () => {
      currentProvider = p;
      updateModelHint();
      updateProviderVisibility();
    });
    const span = document.createElement("span");
    span.textContent =
      p === "anthropic" ? "Anthropic (Claude)" :
      p === "openai" ? "OpenAI" :
      p === "ollama" ? "Ollama (local)" : p;
    label.appendChild(input);
    label.appendChild(span);
    wrap.appendChild(label);
  }
}

function fillCookieBrowsers(names, active) {
  const sel = $("cookies-browser");
  sel.replaceChildren();
  const off = document.createElement("option");
  off.value = "";
  off.textContent = "Off";
  sel.appendChild(off);
  for (const n of names) {
    const o = document.createElement("option");
    o.value = n;
    o.textContent = n.charAt(0).toUpperCase() + n.slice(1);
    sel.appendChild(o);
  }
  sel.value = active;
}

function updateModelHint() {
  const hint = $("model-hint");
  const def = defaultModels[currentProvider];
  hint.textContent = def ? `Leave blank for default: ${def}` : "";
}

function updateProviderVisibility() {
  document.querySelectorAll(".ollama-field").forEach((el) => {
    el.classList.toggle("hidden", currentProvider !== "ollama");
  });
}

async function save() {
  const btn = $("save-btn");
  const msg = $("save-msg");
  btn.disabled = true;
  msg.className = "save-msg";
  msg.textContent = "Saving...";

  const body = {
    audio_root: $("audio-root").value.trim() || null,
    video_root: $("video-root").value.trim() || null,
    provider: currentProvider,
    model: $("model").value.trim() || null,
  };

  const ak = $("anthropic-key").value.trim();
  if (ak === "CLEAR") body.anthropic_api_key = "";
  else if (ak) body.anthropic_api_key = ak;

  const ok = $("openai-key").value.trim();
  if (ok === "CLEAR") body.openai_api_key = "";
  else if (ok) body.openai_api_key = ok;

  const ollUrl = $("ollama-url").value.trim();
  body.ollama_url = ollUrl || "";
  body.cookies_from_browser = $("cookies-browser").value || "";

  const promptValue = $("prompt").value;
  if (!promptValue.trim() || promptValue.trim() === defaultPrompt.trim()) {
    body.categorize_prompt = "";
  } else {
    body.categorize_prompt = promptValue;
  }

  try {
    const res = await fetch(`${HELPER}/config`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const text = await res.text();
      let m = text;
      try { m = JSON.parse(text).detail || text; } catch {}
      throw new Error(m);
    }
    msg.className = "save-msg ok";
    msg.textContent = "Saved.";
    await load();
    setTimeout(() => { msg.textContent = ""; msg.className = "save-msg"; }, 2500);
  } catch (e) {
    msg.className = "save-msg err";
    msg.textContent = `Save failed: ${e.message || e}`;
  } finally {
    btn.disabled = false;
  }
}

async function testKey(provider) {
  let target, body;
  if (provider === "ollama") {
    target = "ollama-url";
    body = { provider, url: $("ollama-url").value.trim() || null };
  } else {
    target = provider === "anthropic" ? "anthropic-key" : "openai-key";
    body = { provider, key: $(target).value.trim() || null };
  }
  const statusEl = $(`${target}-status`);
  statusEl.className = "muted";
  statusEl.textContent = "Testing...";
  try {
    const res = await fetch(`${HELPER}/test-key`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (data.ok) {
      statusEl.className = "muted ok";
      let msg = "Works.";
      if (provider === "ollama" && data.models) {
        msg = data.models.length
          ? `Reachable. Models: ${data.models.slice(0, 6).join(", ")}${data.models.length > 6 ? "..." : ""}`
          : "Reachable, but no models installed. Run: ollama pull llama3.1:8b";
      }
      statusEl.textContent = msg;
    } else {
      statusEl.className = "muted err";
      statusEl.textContent = `Failed: ${data.error || "Unknown error"}`;
    }
  } catch (e) {
    statusEl.className = "muted err";
    statusEl.textContent = `Test failed: ${e.message || e}`;
  }
}

document.querySelectorAll("button.reveal").forEach((btn) => {
  btn.addEventListener("click", () => {
    const input = $(btn.dataset.target);
    input.type = input.type === "password" ? "text" : "password";
  });
});

document.querySelectorAll("button.test").forEach((btn) => {
  btn.addEventListener("click", () => testKey(btn.dataset.provider));
});

$("reset-prompt").addEventListener("click", () => {
  $("prompt").value = defaultPrompt;
  $("prompt-status").textContent = "Reverted to default (not yet saved).";
});

const PRESET_LABELS = {
  notion: "Light red",
  solid: "Solid red",
  outline: "Outline",
  dark: "Dark",
};

let buttonStyle = { ...CF_DEFAULT_STYLE };

function paintPreview() {
  const wrap = $("btn-preview");
  cfApplyStyle(wrap, buttonStyle);
  const main = $("preview-main");
  main.replaceChildren();
  if (buttonStyle.icon) {
    const img = document.createElement("img");
    img.className = "cf-icon";
    img.src = chrome.runtime.getURL("icons/icon-32.png");
    img.alt = "";
    main.appendChild(img);
  }
  const span = document.createElement("span");
  span.textContent = buttonStyle.label;
  main.appendChild(span);
  $("btn-radius-val").textContent = `${buttonStyle.radius}px`;
  document.querySelectorAll("#style-presets .preset").forEach((b) => {
    b.classList.toggle("active", b.dataset.preset === buttonStyle.preset);
  });
}

function fillButtonInputs() {
  $("btn-label").value = buttonStyle.label;
  for (const key of ["bg", "fg", "border"]) {
    $(`btn-${key}`).value = /^#[0-9a-f]{6}$/i.test(buttonStyle[key]) ? buttonStyle[key] : "#000000";
    $(`btn-${key}-text`).value = buttonStyle[key];
  }
  $("btn-radius").value = buttonStyle.radius;
  $("btn-icon").checked = buttonStyle.icon;
}

async function commitButtonStyle({ custom = true } = {}) {
  if (custom) buttonStyle.preset = "custom";
  buttonStyle = cfNormalizeStyle({ ...buttonStyle, preset: buttonStyle.preset });
  paintPreview();
  await cfSaveStyle(buttonStyle);
  const st = $("btn-status");
  st.textContent = "Saved.";
  st.className = "muted ok";
  setTimeout(() => { st.textContent = ""; st.className = "muted"; }, 1600);
}

function wireButtonCustomiser() {
  const wrap = $("style-presets");
  for (const [name, label] of Object.entries(PRESET_LABELS)) {
    const b = document.createElement("button");
    b.className = "preset";
    b.type = "button";
    b.dataset.preset = name;
    b.textContent = label;
    b.addEventListener("click", async () => {
      buttonStyle = cfNormalizeStyle({ preset: name });
      fillButtonInputs();
      await commitButtonStyle({ custom: false });
    });
    wrap.appendChild(b);
  }

  $("btn-label").addEventListener("input", (e) => {
    buttonStyle.label = e.target.value;
    paintPreview();
  });
  $("btn-label").addEventListener("change", () => commitButtonStyle());

  for (const key of ["bg", "fg", "border"]) {
    $(`btn-${key}`).addEventListener("input", (e) => {
      buttonStyle[key] = e.target.value;
      $(`btn-${key}-text`).value = e.target.value;
      paintPreview();
    });
    $(`btn-${key}`).addEventListener("change", () => commitButtonStyle());
    $(`btn-${key}-text`).addEventListener("change", (e) => {
      buttonStyle[key] = e.target.value.trim() || "transparent";
      fillButtonInputs();
      commitButtonStyle();
    });
  }

  $("btn-radius").addEventListener("input", (e) => {
    buttonStyle.radius = Number(e.target.value);
    paintPreview();
  });
  $("btn-radius").addEventListener("change", () => commitButtonStyle());

  $("btn-icon").addEventListener("change", (e) => {
    buttonStyle.icon = e.target.checked;
    commitButtonStyle();
  });

  $("btn-reset").addEventListener("click", async () => {
    buttonStyle = { ...CF_DEFAULT_STYLE };
    fillButtonInputs();
    await commitButtonStyle({ custom: false });
  });
}

async function loadButtonStyle() {
  buttonStyle = await cfLoadStyle();
  fillButtonInputs();
  paintPreview();
}

async function loadPathPresets() {
  const wrap = $("path-presets");
  wrap.innerHTML = "";
  let presets = [];
  try {
    const res = await fetch(`${HELPER}/path-presets`);
    if (!res.ok) return;
    presets = (await res.json()).presets || [];
  } catch {
    return;
  }
  for (const p of presets) {
    const b = document.createElement("button");
    b.className = "preset";
    b.type = "button";
    b.textContent = p.label;
    b.title = `${p.audio}\n${p.video}`;
    b.addEventListener("click", () => {
      $("audio-root").value = p.audio;
      $("video-root").value = p.video;
      markActivePreset(presets);
    });
    wrap.appendChild(b);
  }
  markActivePreset(presets);
}

function markActivePreset(presets) {
  const current = $("audio-root").value.trim();
  const buttons = [...$("path-presets").querySelectorAll(".preset")];
  buttons.forEach((b, i) => b.classList.toggle("active", presets[i]?.audio === current));
}

async function loadHelperInfo() {
  const el = $("helper-version");
  try {
    const res = await fetch(`${HELPER}/status`, { cache: "no-store" });
    if (!res.ok) throw new Error(res.statusText);
    const s = await res.json();
    el.textContent = `Helper ${s.version} · yt-dlp ${s.yt_dlp_version || "not installed"}`;
  } catch {
    el.textContent = "Helper not running.";
  }
}

async function waitForHelper(timeoutMs = 20000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    try {
      const res = await fetch(`${HELPER}/status`, { cache: "no-store" });
      if (res.ok) return true;
    } catch {}
    await new Promise((r) => setTimeout(r, 500));
  }
  return false;
}

async function updateYtDlp() {
  const btn = $("update-ytdlp");
  const st = $("ytdlp-status");
  btn.disabled = true;
  st.className = "muted";
  st.textContent = "Upgrading yt-dlp...";
  try {
    const res = await fetch(`${HELPER}/update/yt-dlp`, { method: "POST" });
    const text = await res.text();
    let data = {};
    try { data = JSON.parse(text); } catch {}
    if (!res.ok) throw new Error(data.detail || text || res.statusText);
    if (data.updated) {
      st.textContent = `Updated ${data.before} → ${data.after}. Restarting helper...`;
      await new Promise((r) => setTimeout(r, 1500));
      const back = await waitForHelper();
      st.className = back ? "muted ok" : "muted err";
      st.textContent = back
        ? `Updated ${data.before} → ${data.after}.`
        : "Helper did not come back. Run: helper/service.sh status";
    } else {
      st.className = "muted ok";
      st.textContent = `Already the latest release (${data.after}).`;
    }
  } catch (e) {
    st.className = "muted err";
    st.textContent = `Update failed: ${e.message || e}`;
  } finally {
    btn.disabled = false;
    loadHelperInfo();
  }
}

$("save-btn").addEventListener("click", save);
$("update-ytdlp").addEventListener("click", updateYtDlp);

load().then(loadPathPresets);
loadHelperInfo();
wireButtonCustomiser();
loadButtonStyle();
$("audio-root").addEventListener("input", () => {
  const wrap = $("path-presets");
  wrap.querySelectorAll(".preset").forEach((b) => b.classList.remove("active"));
});
