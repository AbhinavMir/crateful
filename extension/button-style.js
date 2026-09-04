const CF_PRESETS = {
  notion: { label: "Download", bg: "#FDECEC", fg: "#B42318", border: "#F5C6C4", radius: 8, icon: true },
  solid: { label: "Download", bg: "#CC0000", fg: "#FFFFFF", border: "#CC0000", radius: 18, icon: false },
  outline: { label: "Download", bg: "transparent", fg: "#F1F1F1", border: "#5A5A5A", radius: 18, icon: false },
  dark: { label: "Download", bg: "#2A2A2A", fg: "#F1F1F1", border: "#3F3F3F", radius: 8, icon: true },
};

const CF_DEFAULT_STYLE = { preset: "notion", ...CF_PRESETS.notion };
const CF_STYLE_KEY = "crateful-button-style";

function cfNormalizeStyle(raw) {
  const base = CF_PRESETS[raw?.preset] || CF_PRESETS.notion;
  const merged = { ...CF_DEFAULT_STYLE, ...base, ...(raw || {}) };
  merged.label = String(merged.label ?? "Download").slice(0, 24).trim() || "Download";
  merged.radius = Math.max(0, Math.min(24, Number(merged.radius) || 0));
  merged.icon = !!merged.icon;
  return merged;
}

async function cfLoadStyle() {
  try {
    const got = await chrome.storage.local.get(CF_STYLE_KEY);
    return cfNormalizeStyle(got?.[CF_STYLE_KEY]);
  } catch {
    return { ...CF_DEFAULT_STYLE };
  }
}

async function cfSaveStyle(style) {
  await chrome.storage.local.set({ [CF_STYLE_KEY]: cfNormalizeStyle(style) });
}

function cfApplyStyle(wrap, style) {
  wrap.style.setProperty("--cf-bg", style.bg);
  wrap.style.setProperty("--cf-fg", style.fg);
  wrap.style.setProperty("--cf-border", style.border);
  wrap.style.setProperty("--cf-radius", `${style.radius}px`);
}
