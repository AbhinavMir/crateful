(function () {
  // The background worker re-injects this file after an extension reload, and
  // Chrome may also have injected it already. Running twice would attach a
  // second MutationObserver to the page, so bail out if we are already here.
  if (window.__cratefulContentLoaded) return;
  window.__cratefulContentLoaded = true;

  // Lets the background worker tell a live script from an orphaned one.
  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg?.type === "crateful-ping") sendResponse({ alive: true });
  });

  const HELPER = "http://127.0.0.1:7531";
  const WRAP_ID = "ytd-dj-buttons";
  const MENU_ID = "crateful-menu";

  let menuEl = null;
  let mainBtn = null;
  let caretBtn = null;
  // Cached folder lists, keyed by root. Refreshed each time the menu opens.
  const folderCache = { audio: null, video: null };

  function findAnchor() {
    return (
      document.querySelector("#top-level-buttons-computed") ||
      document.querySelector("ytd-menu-renderer #top-level-buttons-computed") ||
      document.querySelector("#actions #actions-inner") ||
      document.querySelector("#actions-inner")
    );
  }

  function setState(btn, state, text) {
    btn.className = btn.dataset.baseClass + (state ? " ytd-dj-" + state : "");
    btn.textContent = text;
  }

  function setIdle() {
    delete mainBtn.dataset.downloadedPath;
    delete mainBtn.dataset.downloadedRoot;
    mainBtn.title = "Download audio, filed by AI";
    mainBtn.disabled = false;
    setState(mainBtn, null, "Download");
  }

  function setDownloaded(root, relPath) {
    mainBtn.dataset.downloadedPath = relPath;
    mainBtn.dataset.downloadedRoot = root;
    mainBtn.disabled = false;
    mainBtn.title = `Saved at ${relPath} — click to show in Finder`;
    setState(mainBtn, "done", "Downloaded");
  }

  async function reveal(root, path) {
    try {
      await fetch(`${HELPER}/reveal?root=${root}&path=${encodeURIComponent(path)}`,
                  { method: "POST" });
    } catch (e) {
      console.error("[Crateful] reveal failed", e);
    }
  }

  // --- the download itself --------------------------------------------------

  // `folder` null means let the AI file it. A string means put it exactly there.
  async function download({ kind = "audio", folder = null } = {}) {
    closeMenu();
    mainBtn.disabled = true;
    const verb = folder === null ? "Filing" : "Downloading";
    setState(mainBtn, null, `${verb}…`);
    try {
      const body = { url: location.href, kind };
      if (folder !== null) body.folder = folder;
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
      const data = JSON.parse(text);
      setState(mainBtn, "ok", `Saved → ${data.folder || "library"}`);
      folderCache[kind] = null; // a new folder may exist now
      setTimeout(() => setDownloaded(data.kind, data.rel_path), 2200);
    } catch (e) {
      const msg = e.message || String(e);
      const isYtDlp = /yt-dlp/i.test(msg);
      const isHelperDown = /failed to fetch|networkerror/i.test(msg);
      mainBtn.title = msg;
      setState(
        mainBtn,
        "err",
        isYtDlp ? "yt-dlp failed — update in Settings"
          : isHelperDown ? "Helper not running"
          : msg.length > 46 ? msg.slice(0, 43) + "…" : msg,
      );
      setTimeout(setIdle, isYtDlp || isHelperDown ? 8000 : 4000);
    } finally {
      mainBtn.disabled = false;
    }
  }

  // --- the folder menu ------------------------------------------------------

  async function fetchFolders(root) {
    if (folderCache[root]) return folderCache[root];
    const res = await fetch(`${HELPER}/folders?root=${root}`);
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    folderCache[root] = { folders: data.folders || [], recent: data.recent || [] };
    return folderCache[root];
  }

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  function closeMenu() {
    if (menuEl) {
      menuEl.remove();
      menuEl = null;
      document.removeEventListener("keydown", onMenuKey, true);
    }
  }

  // YouTube re-renders the page around us, so the menu node can vanish without
  // closeMenu ever running. Trusting the variable alone would leave menuEl set
  // and the next click on the caret would toggle nothing at all.
  function menuIsOpen() {
    if (menuEl && !menuEl.isConnected) menuEl = null;
    return menuEl !== null;
  }

  function onMenuKey(e) {
    if (e.key === "Escape") { e.stopPropagation(); closeMenu(); }
  }

  // The action row sits low on the page, so a menu anchored below the caret
  // usually runs off the bottom of the window. Flip it above when there is
  // more room up there, and cap its height to whatever room is left.
  function positionMenu() {
    if (!menuEl) return;
    const GAP = 8;
    const r = caretBtn.getBoundingClientRect();
    const below = window.innerHeight - r.bottom - GAP * 2;
    const above = r.top - GAP * 2;
    const flip = below < Math.min(menuEl.scrollHeight, 240) && above > below;

    menuEl.style.maxHeight = `${Math.max(180, Math.min(420, flip ? above : below))}px`;
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

    menuEl = el("div", "crateful-menu");
    menuEl.id = MENU_ID;
    menuEl.addEventListener("click", (e) => e.stopPropagation());

    const tabs = el("div", "crateful-tabs");
    const search = el("input", "crateful-search");
    search.type = "search";
    search.placeholder = "Filter folders…";
    const list = el("div", "crateful-list");
    const foot = el("div", "crateful-foot");

    let root = "audio";

    function renderList(data, query) {
      list.replaceChildren();
      const q = (query || "").toLowerCase().trim();

      const aiRow = el("button", "crateful-item crateful-ai",
                       root === "audio" ? "Let AI pick the folder" : "Let AI pick (video)");
      aiRow.addEventListener("click", () => download({ kind: root }));
      list.appendChild(aiRow);

      const matches = (f) => !q || f.toLowerCase().includes(q);
      const recent = data.recent.filter(matches);
      const rest = data.folders.filter((f) => matches(f) && !recent.includes(f));

      if (recent.length) {
        list.appendChild(el("div", "crateful-head", "Recent"));
        recent.forEach((f) => list.appendChild(folderRow(f)));
      }
      if (rest.length) {
        list.appendChild(el("div", "crateful-head", recent.length ? "All folders" : "Folders"));
        rest.forEach((f) => list.appendChild(folderRow(f)));
      }
      if (!recent.length && !rest.length) {
        if (q) {
          const mk = el("button", "crateful-item crateful-new", `Create "${q}" and download here`);
          mk.addEventListener("click", () => download({ kind: root, folder: q }));
          list.appendChild(mk);
        } else {
          list.appendChild(el("div", "crateful-empty", "No folders yet."));
        }
      }
    }

    function folderRow(folder) {
      const row = el("button", "crateful-item", folder);
      row.title = `Download here without asking the AI`;
      row.addEventListener("click", () => download({ kind: root, folder }));
      return row;
    }

    async function load() {
      list.replaceChildren();
      list.appendChild(el("div", "crateful-empty", "Loading…"));
      try {
        renderList(await fetchFolders(root), search.value);
      } catch (e) {
        list.replaceChildren();
        list.appendChild(el("div", "crateful-empty", "Helper not running."));
      }
      positionMenu();
    }

    for (const r of ["audio", "video"]) {
      const t = el("button", "crateful-tab" + (r === root ? " active" : ""),
                   r === "audio" ? "Audio" : "Video");
      t.addEventListener("click", () => {
        root = r;
        menuEl.querySelectorAll(".crateful-tab").forEach((x) => x.classList.remove("active"));
        t.classList.add("active");
        load();
      });
      tabs.appendChild(t);
    }

    search.addEventListener("input", () => {
      const cached = folderCache[root];
      if (cached) renderList(cached, search.value);
    });

    const settings = el("button", "crateful-link", "Settings ⚙");
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
  }

  document.addEventListener("click", () => closeMenu());

  // --- injection ------------------------------------------------------------

  async function applyExistingStatus() {
    try {
      const res = await fetch(`${HELPER}/check?url=${encodeURIComponent(location.href)}`);
      if (!res.ok) return;
      const data = await res.json();
      if (data.audio) setDownloaded("audio", data.audio);
      else if (data.video) setDownloaded("video", data.video);
    } catch (e) {
      // Helper not running. Leave the button in its default state.
    }
  }

  function injectButtons() {
    if (!location.href.includes("youtube.com/watch")) return;
    if (document.getElementById(WRAP_ID)) return;
    const anchor = findAnchor();
    if (!anchor) return;

    const wrap = el("span", null);
    wrap.id = WRAP_ID;

    mainBtn = el("button", "ytd-dj-btn ytd-dj-main");
    mainBtn.dataset.baseClass = "ytd-dj-btn ytd-dj-main";
    mainBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      if (mainBtn.dataset.downloadedPath) {
        reveal(mainBtn.dataset.downloadedRoot, mainBtn.dataset.downloadedPath);
        return;
      }
      download({ kind: "audio" });
    });
    setIdle();

    caretBtn = el("button", "ytd-dj-btn ytd-dj-more", "⋮");
    caretBtn.dataset.baseClass = "ytd-dj-btn ytd-dj-more";
    caretBtn.title = "Choose a folder, or download the video";
    caretBtn.setAttribute("aria-label", "Download options");
    caretBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      openMenu();
    });

    wrap.append(mainBtn, caretBtn);
    anchor.appendChild(wrap);
    applyExistingStatus();
  }

  let lastUrl = location.href;
  const observer = new MutationObserver(() => {
    if (location.href !== lastUrl) {
      lastUrl = location.href;
      closeMenu();
      const existing = document.getElementById(WRAP_ID);
      if (existing) existing.remove();
      folderCache.audio = folderCache.video = null;
    }
    injectButtons();
  });
  observer.observe(document.body, { childList: true, subtree: true });

  setTimeout(injectButtons, 800);
  setTimeout(injectButtons, 2000);
})();
