globalThis.CF_PRESETS = {
  notion: { label: "Download", bg: "#FDECEC", fg: "#B42318", border: "#F5C6C4", radius: 8, icon: true },
  solid: { label: "Download", bg: "#CC0000", fg: "#FFFFFF", border: "#CC0000", radius: 18, icon: false },
  outline: { label: "Download", bg: "transparent", fg: "#F1F1F1", border: "#5A5A5A", radius: 18, icon: false },
  dark: { label: "Download", bg: "#2A2A2E", fg: "#F1F1F1", border: "#3F3F3F", radius: 8, icon: true },
};

globalThis.CF_DEFAULT_STYLE = { preset: "notion", ...globalThis.CF_PRESETS.notion };
globalThis.CF_STYLE_KEY = "crateful-button-style";

globalThis.cfNormalizeStyle = function (raw) {
  const base = globalThis.CF_PRESETS[raw?.preset] || globalThis.CF_PRESETS.notion;
  const merged = { ...globalThis.CF_DEFAULT_STYLE, ...base, ...(raw || {}) };
  merged.label = String(merged.label ?? "Download").slice(0, 24).trim() || "Download";
  merged.radius = Math.max(0, Math.min(24, Number(merged.radius) || 0));
  merged.icon = !!merged.icon;
  return merged;
};

globalThis.cfLoadStyle = async function () {
  try {
    const got = await chrome.storage.local.get(globalThis.CF_STYLE_KEY);
    return globalThis.cfNormalizeStyle(got?.[globalThis.CF_STYLE_KEY]);
  } catch {
    return { ...globalThis.CF_DEFAULT_STYLE };
  }
};

globalThis.cfSaveStyle = async function (style) {
  await chrome.storage.local.set({ [globalThis.CF_STYLE_KEY]: globalThis.cfNormalizeStyle(style) });
};

globalThis.cfApplyStyle = function (wrap, style) {
  wrap.style.setProperty("--cf-bg", style.bg);
  wrap.style.setProperty("--cf-fg", style.fg);
  wrap.style.setProperty("--cf-border", style.border);
  wrap.style.setProperty("--cf-radius", `${style.radius}px`);
};
