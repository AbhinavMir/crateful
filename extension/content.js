(function () {
  if (window.__cratefulContentLoaded) return;
  window.__cratefulContentLoaded = true;

  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg?.type === "crateful-ping") sendResponse({ alive: true });
  });

  const HELPER = "http://127.0.0.1:7531";
  const WRAP_ID = "crateful-buttons";

  const isPlaylistPage = () => location.pathname.startsWith("/playlist");
  const isWatchPage = () => location.pathname.startsWith("/watch");

  let menuEl = null;
  let wrapEl = null;
  let mainBtn = null;
  let caretBtn = null;
  let style = { ...CF_DEFAULT_STYLE };
  let playlistPromise = null;

  let running = null;
  let playlistCache = null;

  let existing = { audio: null, video: null };
  const folderCache = { audio: null, video: null };

  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  };

  function firstVisible(selectors) {
    for (const sel of selectors) {
      for (const node of document.querySelectorAll(sel)) {
        const r = node.getBoundingClientRect();
        if (r.width > 0 && r.height > 0 && node.offsetParent !== null) return node;
      }
    }
    return null;
  }

  const PLAYLIST_ANCHORS = [
    ".ytFlexibleActionsViewModelActionRow",
    "yt-flexible-actions-view-model",
    "ytd-playlist-header-renderer #top-level-buttons-computed",
    ".metadata-buttons-wrapper",
    "ytd-playlist-sidebar-primary-info-renderer #menu",
  ];
  const WATCH_ANCHORS = [
    "#top-level-buttons-computed",
    "ytd-menu-renderer #top-level-buttons-computed",
    "#actions #actions-inner",
    "#actions-inner",
  ];

  function findAnchor() {
    return firstVisible(isPlaylistPage() ? PLAYLIST_ANCHORS : WATCH_ANCHORS);
  }

  function renderMain(state, text) {
    mainBtn.className = "cf-btn cf-main" + (state ? " cf-" + state : "");
    mainBtn.replaceChildren();
    if (style.icon && !state) {
      const img = el("img", "cf-icon");
      img.src = chrome.runtime.getURL("icons/icon-32.png");
      img.alt = "";
      mainBtn.appendChild(img);
    }
    mainBtn.appendChild(el("span", "cf-label", text));
  }

  function setIdle() {
    mainBtn.disabled = false;
    if (isPlaylistPage()) {
      const n = playlistCache?.count;
      mainBtn.title = "Download every video in this playlist, each filed on its own";
      renderMain(null, n ? `${style.label} ${n}` : style.label);
      return;
    }
    const done = existing.audio || existing.video;
    if (done) {
      mainBtn.title = `Already downloaded: ${done}. Click to show in Finder.`;
      renderMain("done", "Downloaded");
    } else {
      mainBtn.title = `${style.label} audio, filed by AI`;
      renderMain(null, style.label);
    }
  }

  async function reveal(root, path) {
    try {
      await fetch(`${HELPER}/reveal?root=${root}&path=${encodeURIComponent(path)}`,
                  { method: "POST" });
    } catch (e) {
      console.error("[Crateful] reveal failed", e);
    }
  }

  async function download({ kind = "audio", folder = null, force = false, url = null } = {}) {
    closeMenu();
    mainBtn.disabled = true;
    renderMain(null, (force ? "Replacing" : folder === null ? "Filing" : "Downloading") + "…");
    try {
      const data = await postDownload({ kind, folder, force, url });
      if (data.ai_error) {
        mainBtn.title = `Saved to ${data.folder}. AI filing unavailable: ${data.ai_error}`;
        renderMain("warn", `Saved → ${data.folder} (no AI)`);
      } else {
        mainBtn.title = `Saved at ${data.rel_path}`;
        renderMain("ok", `Saved → ${data.folder || "library"}`);
      }
      folderCache[kind] = null;
      existing[kind] = data.rel_path;
      setTimeout(setIdle, 2200);
    } catch (e) {
      showError(e);
    } finally {
      mainBtn.disabled = false;
    }
  }

  async function postDownload({ kind, folder, force, url }) {
    const body = { url: url || location.href, kind };
    if (folder !== null && folder !== undefined) body.folder = folder;
    if (force) body.force = true;
    const res = await fetch(`${HELPER}/download`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const text = await res.text();
    if (!res.ok) {
      let msg = text;
      try { msg = JSON.parse(text).detail || text; } catch (_) {}
      throw new Error(msg);
    }
    return JSON.parse(text);
  }

  function showError(e) {
    const msg = e.message || String(e);
    const isYtDlp = /yt-dlp/i.test(msg);
    const isDown = /failed to fetch|networkerror/i.test(msg);
    const isKey = /api key|rate limit/i.test(msg);
    mainBtn.title = msg;
    renderMain("err",
      isKey ? "AI key rejected — see Settings"
        : isYtDlp ? "yt-dlp failed — update in Settings"
        : isDown ? "Helper not running"
        : msg.length > 46 ? msg.slice(0, 43) + "…" : msg);
    setTimeout(setIdle, isYtDlp || isDown || isKey ? 8000 : 4000);
  }

  async function alreadyHave(entries, kind) {
    try {
      const res = await fetch(`${HELPER}/check-bulk`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ video_ids: entries.map((e) => e.video_id) }),
      });
      if (!res.ok) return new Set();
      const d = await res.json();
      return new Set(
        Object.entries(d.found || {})
          .filter(([, kinds]) => kinds[kind])
          .map(([vid]) => vid),
      );
    } catch {
      return new Set();
    }
  }

  async function downloadPlaylist(entries, { kind = "audio", folder = null, skipExisting = true } = {}) {
    closeMenu();
    if (running) { running.cancelled = true; return; }

    const run = { cancelled: false };
    running = run;
    mainBtn.disabled = false;
    mainBtn.title = "Click to stop after the current track";

    const have = skipExisting ? await alreadyHave(entries, kind) : new Set();
    const queue = entries.filter((e) => !have.has(e.video_id));
    let done = 0, failed = 0, unfiled = 0;
    const skipped = entries.length - queue.length;

    for (const entry of queue) {
      if (run.cancelled) break;
      renderMain("busy", `${done + failed + 1}/${queue.length}…`);
      try {
        const r = await postDownload({ kind, folder, force: false, url: entry.url });
        if (r.ai_error) unfiled++;
        done++;
      } catch (e) {
        failed++;
        console.warn("[Crateful] playlist entry failed", entry.url, e);
      }
    }

    running = null;
    folderCache[kind] = null;
    const bits = [`${done} saved`];
    if (skipped) bits.push(`${skipped} already had`);
    if (unfiled) bits.push(`${unfiled} unsorted`);
    if (failed) bits.push(`${failed} failed`);
    if (run.cancelled) bits.push("stopped");
    renderMain(failed || run.cancelled ? "err" : "ok", bits.join(", "));
    mainBtn.disabled = false;
    refreshExisting();
    setTimeout(setIdle, 6000);
  }

  async function fetchFolders(root) {
    if (folderCache[root]) return folderCache[root];
    const res = await fetch(`${HELPER}/folders?root=${root}`);
    if (!res.ok) throw new Error(await res.text());
    const d = await res.json();
    folderCache[root] = { folders: d.folders || [], recent: d.recent || [] };
    return folderCache[root];
  }

  function primePlaylist() {
    playlistPromise = null;
    if (!/[?&]list=/.test(location.href)) return;
    const listUrl = location.href;
    playlistPromise = (async () => {
      try {
        const res = await fetch(`${HELPER}/playlist?url=${encodeURIComponent(listUrl)}`);
        if (!res.ok) return null;
        const d = await res.json();
        return d.is_playlist ? d : null;
      } catch {
        return null;
      }
    })();
    playlistPromise.then((p) => {
      playlistCache = p;
      if (mainBtn && !running) setIdle();
    });
  }

  async function refreshExisting() {
    try {
      const res = await fetch(`${HELPER}/check?url=${encodeURIComponent(location.href)}`);
      if (!res.ok) return;
      const d = await res.json();
      existing = { audio: d.audio || null, video: d.video || null };
    } catch {
      existing = { audio: null, video: null };
    }
    if (mainBtn) setIdle();
  }

  function closeMenu() {
    if (menuEl) {
      menuEl.remove();
      menuEl = null;
      document.removeEventListener("keydown", onMenuKey, true);
    }
  }

  function onMenuKey(e) {
    if (e.key === "Escape") { e.stopPropagation(); closeMenu(); }
  }

  function menuIsOpen() {
    if (menuEl && !menuEl.isConnected) menuEl = null;
    return menuEl !== null;
  }

  function positionMenu() {
    if (!menuEl) return;
    const GAP = 8;
    const r = caretBtn.getBoundingClientRect();
    const below = window.innerHeight - r.bottom - GAP * 2;
    const above = r.top - GAP * 2;
    const flip = below < Math.min(menuEl.scrollHeight, 240) && above > below;
    menuEl.style.maxHeight = `${Math.max(180, Math.min(440, flip ? above : below))}px`;
    const height = Math.min(menuEl.offsetHeight, flip ? above : below);
    menuEl.style.top = flip
      ? `${window.scrollY + r.top - GAP - height}px`
      : `${window.scrollY + r.bottom + GAP}px`;
    menuEl.style.left = `${Math.max(GAP, Math.min(
      window.scrollX + r.right - menuEl.offsetWidth,
      window.scrollX + window.innerWidth - menuEl.offsetWidth - GAP))}px`;
  }

  function openMenu() {
    if (menuIsOpen()) { closeMenu(); return; }

    menuEl = el("div", "cf-menu");
    menuEl.id = "crateful-menu";
    menuEl.addEventListener("click", (e) => e.stopPropagation());

    const tabs = el("div", "cf-tabs");
    const search = el("input", "cf-search");
    search.type = "search";
    search.placeholder = "Filter folders…";
    const list = el("div", "cf-list");
    const foot = el("div", "cf-foot");

    let root = "audio";
    let playlist = null;
    let playlistPending = playlistPromise !== null;

    function actionRow(cls, text, onClick, subtitle) {
      const b = el("button", "cf-item " + cls);
      b.appendChild(el("span", "cf-item-main", text));
      if (subtitle) b.appendChild(el("span", "cf-item-sub", subtitle));
      b.addEventListener("click", onClick);
      return b;
    }

    function renderList(data, query) {
      list.replaceChildren();
      const q = (query || "").toLowerCase().trim();
      const have = isPlaylistPage() ? null : existing[root];

      if (have && !q) {
        list.appendChild(el("div", "cf-head", "Already downloaded"));
        list.appendChild(actionRow("cf-have", have, () => { closeMenu(); reveal(root, have); },
                                   "Open in Finder"));
        list.appendChild(actionRow("cf-again", "Download again",
                                   () => download({ kind: root, force: true }),
                                   "Replaces the file above"));
      }

      if (playlistPending && !q) {
        list.appendChild(el("div", "cf-head", "Playlist"));
        list.appendChild(el("div", "cf-empty cf-pending", "Checking playlist…"));
      } else if (playlist && !q) {
        list.appendChild(el("div", "cf-head", "Playlist"));
        list.appendChild(actionRow(
          "cf-playlist",
          `Download all ${playlist.count}, AI filed`,
          () => downloadPlaylist(playlist.entries, { kind: root }),
          playlist.title || undefined,
        ));
        list.appendChild(actionRow(
          "cf-playlist-all",
          `Download all ${playlist.count}, including ones I have`,
          () => downloadPlaylist(playlist.entries, { kind: root, skipExisting: false }),
          "Skips nothing",
        ));
      }

      const forPlaylist = isPlaylistPage() && playlist;
      const pick = (folder) => (forPlaylist
        ? downloadPlaylist(playlist.entries, { kind: root, folder })
        : download({ kind: root, folder, force: !!have }));

      if (isPlaylistPage() && !playlist) {
        if (!q) list.appendChild(el("div", "cf-empty", "No playlist found on this page."));
        return;
      }

      if (!q) {
        list.appendChild(el("div", "cf-head",
          forPlaylist ? "Put the whole playlist in" : have ? "Download again to" : "Download to"));
      }
      if (!forPlaylist) {
        list.appendChild(actionRow("cf-ai", "Let AI pick the folder",
                                   () => download({ kind: root, force: !!have })));
      }

      const matches = (f) => !q || f.toLowerCase().includes(q);
      const recent = data.recent.filter(matches);
      const rest = data.folders.filter((f) => matches(f) && !recent.includes(f));
      const folderRow = (f) => actionRow("", f, () => pick(f));

      if (recent.length) {
        list.appendChild(el("div", "cf-head", "Recent"));
        recent.forEach((f) => list.appendChild(folderRow(f)));
      }
      if (rest.length) {
        list.appendChild(el("div", "cf-head", recent.length ? "All folders" : "Folders"));
        rest.forEach((f) => list.appendChild(folderRow(f)));
      }
      if (!recent.length && !rest.length && q) {
        list.appendChild(actionRow("cf-new", `Create "${q}" and download here`,
                                   () => pick(q)));
      }
    }

    async function load() {
      list.replaceChildren(el("div", "cf-empty", "Loading…"));
      try {
        renderList(await fetchFolders(root), search.value);
      } catch (e) {
        list.replaceChildren(el("div", "cf-empty", "Helper not running."));
      }
      positionMenu();
    }

    for (const r of ["audio", "video"]) {
      const t = el("button", "cf-tab" + (r === root ? " active" : ""),
                   r === "audio" ? "Audio" : "Video");
      t.addEventListener("click", () => {
        root = r;
        menuEl.querySelectorAll(".cf-tab").forEach((x) => x.classList.remove("active"));
        t.classList.add("active");
        load();
      });
      tabs.appendChild(t);
    }

    search.addEventListener("input", () => {
      const cached = folderCache[root];
      if (cached) renderList(cached, search.value);
    });

    const settings = el("button", "cf-link", "Settings ⚙");
    settings.addEventListener("click", () => {
      closeMenu();
      chrome.runtime.sendMessage({ type: "open-settings" });
    });
    foot.appendChild(settings);

    menuEl.append(tabs, search, list, foot);
    document.body.appendChild(menuEl);
    positionMenu();
    document.addEventListener("keydown", onMenuKey, true);
    search.focus();
    load();

    if (playlistPromise) {
      playlistPromise.then((p) => {
        playlistPending = false;
        playlist = p;
        if (!menuIsOpen()) return;
        const cached = folderCache[root];
        if (cached) { renderList(cached, search.value); positionMenu(); }
      });
    }
  }

  document.addEventListener("click", () => closeMenu());

  function injectButtons() {
    if (!isWatchPage() && !isPlaylistPage()) return;
    if (document.getElementById(WRAP_ID)) return;
    const anchor = findAnchor();
    if (!anchor) return;

    wrapEl = el("span");
    wrapEl.id = WRAP_ID;
    cfApplyStyle(wrapEl, style);

    mainBtn = el("button", "cf-btn cf-main");
    mainBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      if (running) { running.cancelled = true; return; }
      if (isPlaylistPage()) {
        if (playlistCache) downloadPlaylist(playlistCache.entries, { kind: "audio" });
        return;
      }
      const done = existing.audio || existing.video;
      if (done) {
        reveal(existing.audio ? "audio" : "video", done);
        return;
      }
      download({ kind: "audio" });
    });

    caretBtn = el("button", "cf-btn cf-more");
    caretBtn.appendChild(el("span", null, "⋮"));
    caretBtn.title = "Choose a folder, download the video, or download again";
    caretBtn.setAttribute("aria-label", "Download options");
    caretBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      openMenu();
    });

    wrapEl.append(mainBtn, caretBtn);
    anchor.appendChild(wrapEl);
    setIdle();
    if (!isPlaylistPage()) refreshExisting();
    primePlaylist();
  }

  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== "local" || !changes[CF_STYLE_KEY]) return;
    style = cfNormalizeStyle(changes[CF_STYLE_KEY].newValue);
    if (wrapEl) { cfApplyStyle(wrapEl, style); setIdle(); }
  });

  let lastUrl = location.href;
  const observer = new MutationObserver(() => {
    if (location.href !== lastUrl) {
      lastUrl = location.href;
      closeMenu();
      document.getElementById(WRAP_ID)?.remove();
      folderCache.audio = folderCache.video = null;
      existing = { audio: null, video: null };
      playlistPromise = null;
      playlistCache = null;
    }
    injectButtons();
  });
  observer.observe(document.body, { childList: true, subtree: true });

  cfLoadStyle().then((s) => {
    style = s;
    if (wrapEl) { cfApplyStyle(wrapEl, style); setIdle(); }
  });

  setTimeout(injectButtons, 800);
  setTimeout(injectButtons, 2000);
})();
