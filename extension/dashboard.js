(function () {
  if (window.__cratefulDashboard) return;
  window.__cratefulDashboard = true;

  const CSS = `
    :root { color-scheme: dark; }
    html, body { margin: 0; padding: 0; background: #0f0f10; }
    body {
      min-height: 100vh;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      color: #ededed;
      display: flex;
      justify-content: center;
    }
    .cfd-wrap { width: 100%; max-width: 720px; padding: 48px 24px 80px; }
    .cfd-top { display: flex; align-items: center; gap: 14px; margin-bottom: 6px; }
    .cfd-top img { width: 40px; height: 40px; }
    .cfd-top h1 { margin: 0; font-size: 26px; font-weight: 650; letter-spacing: -0.01em; }
    .cfd-sub { margin: 0 0 32px 54px; color: #8b8b8f; font-size: 14px; }
    .cfd-state {
      display: flex; align-items: center; gap: 10px;
      font-size: 15px; margin-bottom: 24px; color: #b9b9be;
    }
    .cfd-dot { width: 9px; height: 9px; border-radius: 50%; background: #444; flex: none; }
    .cfd-dot.live { background: #3fb950; box-shadow: 0 0 0 4px rgba(63,185,80,0.16); }
    .cfd-dot.off { background: #f0883e; }
    .cfd-tools { display: flex; gap: 8px; margin-bottom: 4px; flex-wrap: wrap; }
    .cfd-search {
      flex: 1; min-width: 180px; padding: 9px 12px;
      background: #18181b; border: 1px solid #27272b; border-radius: 9px;
      color: #ededed; font: inherit; font-size: 14px; outline: none;
    }
    .cfd-search:focus { border-color: #3d3d43; }
    .cfd-chip {
      background: #18181b; border: 1px solid #27272b; border-radius: 999px;
      color: #9a9aa0; padding: 8px 14px; font: inherit; font-size: 13px; cursor: pointer;
    }
    .cfd-chip:hover { color: #ededed; border-color: #3d3d43; }
    .cfd-chip.on { background: #2a1f1f; border-color: #5a2f2b; color: #f0b4b0; }
    .cfd-head {
      font-size: 11px; font-weight: 700; letter-spacing: 0.06em;
      text-transform: uppercase; color: #6e6e73; margin: 28px 0 10px;
    }
    .cfd-card {
      background: #18181b; border: 1px solid #27272b; border-radius: 12px;
      padding: 16px 18px; margin-bottom: 10px;
    }
    .cfd-title {
      font-size: 15px; font-weight: 550; margin-bottom: 4px;
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }
    .cfd-meta { font-size: 12.5px; color: #8b8b8f; display: flex; gap: 14px; flex-wrap: wrap; }
    .cfd-bar {
      height: 6px; background: #2a2a2e; border-radius: 999px;
      overflow: hidden; margin: 12px 0 9px;
    }
    .cfd-fill {
      height: 100%; background: #B42318; border-radius: 999px;
      transition: width 0.4s ease;
    }
    .cfd-fill.converting { background: #d0a215; }
    .cfd-card.done { border-color: #1f3b22; }
    .cfd-card.done .cfd-title { color: #8fd48f; }
    .cfd-card.failed { border-color: #4a2020; }
    .cfd-card.failed .cfd-title { color: #f5a3a3; }
    .cfd-empty { color: #6e6e73; font-size: 14px; padding: 6px 0 0; }
    .cfd-foot { margin-top: 40px; font-size: 12px; color: #55555a; }
    .cfd-card.playable { cursor: pointer; }
    .cfd-card.playable:hover { border-color: #3d3d43; background: #1d1d21; }
    .cfd-card.playing { border-color: #B42318; }
    .cfd-player {
      position: sticky; bottom: 0; margin-top: 28px; padding: 14px 16px;
      background: #18181b; border: 1px solid #27272b; border-radius: 12px;
    }
    .cfd-player-top {
      display: flex; align-items: center; gap: 12px; margin-bottom: 10px;
    }
    .cfd-player-top .cfd-title { margin-bottom: 0; flex: 1; min-width: 0; }
    .cfd-close {
      flex: none; width: 34px; height: 34px; line-height: 1;
      background: #24242a; border: 1px solid #34343a; border-radius: 9px;
      color: #c9c9ce; font: inherit; font-size: 20px; cursor: pointer;
    }
    .cfd-close:hover { background: #3a2626; border-color: #5a2f2b; color: #ffb4ae; }
    .cfd-player audio, .cfd-player video { width: 100%; display: block; }
    .cfd-player video { max-height: 320px; border-radius: 8px; background: #000; }
  `;

  const HELPER = "http://127.0.0.1:7531";

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  function fmtBytes(n) {
    if (!n) return null;
    const u = ["B", "KB", "MB", "GB"];
    let i = 0;
    while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
    return `${n < 10 ? n.toFixed(1) : Math.round(n)} ${u[i]}`;
  }

  function fmtEta(s) {
    if (s === null || s === undefined) return null;
    const m = Math.floor(s / 60), r = Math.round(s % 60);
    return m ? `${m}m ${r}s left` : `${r}s left`;
  }

  function build() {
    document.documentElement.replaceChildren();
    const head = el("head");
    const style = el("style");
    style.textContent = CSS;
    const title = el("title", null, "Crateful");
    const meta = el("meta");
    meta.setAttribute("name", "viewport");
    meta.setAttribute("content", "width=device-width, initial-scale=1");
    const icon = el("link");
    icon.rel = "icon";
    icon.href = chrome.runtime.getURL("icons/icon-128.png");
    head.append(meta, title, style, icon);

    const body = el("body");
    const wrap = el("div", "cfd-wrap");
    wrap.id = "crateful-dashboard";
    const top = el("div", "cfd-top");
    const logo = el("img");
    logo.src = chrome.runtime.getURL("icons/icon-128.png");
    logo.alt = "";
    top.append(logo, el("h1", null, "Crateful"));
    const sub = el("p", "cfd-sub", "Downloads on this machine");
    const state = el("div", "cfd-state");
    const dot = el("span", "cfd-dot");
    const stateText = el("span", null, "Connecting…");
    state.append(dot, stateText);
    const tools = el("div", "cfd-tools");
    const search = el("input", "cfd-search");
    search.type = "search";
    search.placeholder = "Search downloads…";
    search.addEventListener("input", () => { query = search.value; render(lastData); });
    tools.appendChild(search);
    for (const [key, label] of [["all", "All"], ["audio", "Audio"], ["video", "Video"]]) {
      const b = el("button", "cfd-chip" + (kindFilter === key ? " on" : ""), label);
      b.addEventListener("click", () => {
        kindFilter = key;
        tools.querySelectorAll(".cfd-chip").forEach((x) => x.classList.remove("on"));
        b.classList.add("on");
        render(lastData);
      });
      tools.appendChild(b);
    }
    const list = el("div");
    const player = el("div", "cfd-player");
    player.hidden = true;
    const foot = el("div", "cfd-foot", "This page is drawn by the Crateful extension.");
    wrap.append(top, sub, state, tools, list, player, foot);
    body.append(wrap);
    document.documentElement.append(head, body);
    return { dot, stateText, list, player };
  }

  let playing = null;
  let lastData = null;
  let query = "";
  let kindFilter = "all";
  let ui = build();

  function reassert() {
    if (!document.getElementById("crateful-dashboard")) {
      ui = build();
      tick();
    }
  }
  document.addEventListener("DOMContentLoaded", reassert);
  window.addEventListener("load", reassert);

  function fileUrl(job) {
    return `${HELPER}/file?root=${encodeURIComponent(job.kind)}&path=${encodeURIComponent(job.rel_path)}`;
  }

  function stop() {
    const media = ui.player.querySelector("audio, video");
    if (media) { media.pause(); media.removeAttribute("src"); media.load(); }
    ui.player.replaceChildren();
    ui.player.hidden = true;
    playing = null;
    render(lastData);
  }

  function play(job) {
    playing = job.rel_path;
    ui.player.hidden = false;
    ui.player.replaceChildren();
    const bar = el("div", "cfd-player-top");
    bar.appendChild(el("div", "cfd-title", job.title || job.rel_path));
    const close = el("button", "cfd-close", "\u00d7");
    close.title = "Close the player";
    close.setAttribute("aria-label", "Close the player");
    close.addEventListener("click", stop);
    bar.appendChild(close);
    ui.player.appendChild(bar);
    const media = el(job.kind === "video" ? "video" : "audio");
    media.controls = true;
    media.autoplay = true;
    media.src = fileUrl(job);
    ui.player.appendChild(media);
    media.play().catch(() => {});
    render(lastData);
  }

  function card(job, finished) {
    const canPlay = finished && job.status === "done" && job.rel_path;
    const c = el("div", "cfd-card" + (finished ? " " + job.status : "")
      + (canPlay ? " playable" : "")
      + (canPlay && job.rel_path === playing ? " playing" : ""));
    if (canPlay) {
      c.title = "Play";
      c.addEventListener("click", () => play(job));
    }
    c.appendChild(el("div", "cfd-title", job.title || job.url));

    if (!finished) {
      const bar = el("div", "cfd-bar");
      const fill = el("div", "cfd-fill" + (job.status === "converting" ? " converting" : ""));
      fill.style.width = `${Math.max(2, job.percent || 0)}%`;
      bar.appendChild(fill);
      c.appendChild(bar);
    }

    const bits = [];
    if (finished) {
      bits.push(job.status === "done" ? "Saved" : "Failed");
      if (job.rel_path) bits.push(job.rel_path);
      if (job.error) bits.push(job.error);
    } else if (job.status === "converting") {
      bits.push("Converting to " + (job.kind === "video" ? "MP4" : "MP3"));
    } else if (job.status === "starting") {
      bits.push("Starting");
    } else {
      bits.push(`${(job.percent || 0).toFixed(0)}%`);
      const got = fmtBytes(job.downloaded_bytes);
      const total = fmtBytes(job.total_bytes);
      if (got && total) bits.push(`${got} of ${total}`);
      const sp = fmtBytes(job.speed);
      if (sp) bits.push(`${sp}/s`);
      const eta = fmtEta(job.eta);
      if (eta) bits.push(eta);
      if (job.folder) bits.push(`→ ${job.folder}`);
    }
    const meta = el("div", "cfd-meta");
    for (const b of bits) meta.appendChild(el("span", null, b));
    c.appendChild(meta);
    return c;
  }

  function matches(job) {
    if (kindFilter !== "all" && job.kind !== kindFilter) return false;
    const q = query.trim().toLowerCase();
    if (!q) return true;
    return [job.title, job.rel_path, job.folder]
      .some((v) => v && String(v).toLowerCase().includes(q));
  }

  function render(data) {
    if (!data) return;
    lastData = data;
    const active = data.active.filter(matches);
    const recent = data.recent.filter(matches);
    const filtering = query.trim() || kindFilter !== "all";

    ui.dot.className = "cfd-dot live";
    ui.stateText.textContent = data.active.length
      ? `${data.active.length} ${data.active.length === 1 ? "download" : "downloads"} in progress`
      : "Nothing downloading";

    ui.list.replaceChildren();
    if (active.length) {
      ui.list.appendChild(el("div", "cfd-head", "In progress"));
      for (const j of active) ui.list.appendChild(card(j, false));
    }
    if (recent.length) {
      ui.list.appendChild(el("div", "cfd-head", "Recent"));
      for (const j of recent) ui.list.appendChild(card(j, true));
    }
    if (!active.length && !recent.length) {
      ui.list.appendChild(el("div", "cfd-empty", filtering
        ? "Nothing matches that."
        : "No downloads yet. Hit Download on a YouTube page."));
    }
  }

  function offline(reason) {
    lastData = null;
    ui.dot.className = "cfd-dot off";
    ui.stateText.textContent = "Helper not running";
    ui.list.replaceChildren();
    ui.list.appendChild(el("div", "cfd-empty", reason || "Start it with helper/run.sh"));
  }

  async function poll() {
    try {
      const resp = await chrome.runtime.sendMessage({ type: "crateful-progress" });
      if (resp && resp.ok) render(resp.data);
      else offline();
    } catch (e) {
      offline();
    }
  }

  let timer = null;

  function schedule() {
    clearTimeout(timer);
    if (document.hidden) return;
    const busy = lastData && lastData.active.length;
    timer = setTimeout(tick, busy ? 1000 : 5000);
  }

  async function tick() {
    await poll();
    schedule();
  }

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) tick();
    else clearTimeout(timer);
  });

  tick();
})();
