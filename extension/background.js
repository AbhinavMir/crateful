// Routes audio commands from the popup to the offscreen document.
//
// The offscreen doc takes a few hundred ms to load its script after
// chrome.offscreen.createDocument resolves, so the popup can't talk to
// it directly without races. Background acts as a proxy: it waits for
// the offscreen's "offscreen-ready" handshake (or a ping response) and
// only then forwards the audio-cmd as audio-cmd-fwd.

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

const OFFSCREEN_URL = "offscreen.html";

// Chrome tears down the content script in every open tab when the extension is
// reloaded or updated, and it does not put it back. Our own updater calls
// chrome.runtime.reload(), which does not fire onInstalled, so the only signal
// we can rely on is this worker starting up. Without this, every YouTube tab
// the user already had open silently loses its download buttons.
//
// Ping each matching tab first: a live content script answers, and only a tab
// whose script is missing or orphaned gets a fresh injection.
const WATCH_MATCH = "*://www.youtube.com/watch*";

async function hasLiveContentScript(tabId) {
  try {
    const resp = await chrome.tabs.sendMessage(tabId, { type: "crateful-ping" });
    return resp?.alive === true;
  } catch (_) {
    // No receiving end: the script is absent or orphaned.
    return false;
  }
}

async function reinjectContentScript() {
  let tabs = [];
  try {
    tabs = await chrome.tabs.query({ url: WATCH_MATCH });
  } catch (e) {
    console.warn("[Crateful] could not list YouTube tabs", e);
    return;
  }
  for (const tab of tabs) {
    if (tab.id == null || tab.discarded) continue;
    if (await hasLiveContentScript(tab.id)) continue;
    try {
      await chrome.scripting.insertCSS({ target: { tabId: tab.id }, files: ["content.css"] });
      await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["content.js"] });
    } catch (e) {
      // A tab we cannot script into. Nothing to do about it.
      console.warn("[Crateful] re-inject failed for tab", tab.id, e);
    }
  }
}

// Runs on every service-worker start, which covers a manual reload, an
// update, and chrome.runtime.reload() from the in-app updater.
reinjectContentScript();

let offscreenReady = false;
let readyWaiters = [];
let creating = null;

function settleReady() {
  if (offscreenReady) return;
  offscreenReady = true;
  const waiters = readyWaiters.slice();
  readyWaiters = [];
  for (const w of waiters) {
    try { w(); } catch (_) {}
  }
}

async function ensureOffscreen() {
  // Already-known-ready fast path.
  if (offscreenReady) return;

  let hasDoc = false;
  try {
    hasDoc = !!(await chrome.offscreen.hasDocument?.());
  } catch (_) {}

  if (hasDoc) {
    // Doc exists but we may have missed (or never got) the ready signal —
    // happens after the service worker is restarted. Try a ping.
    try {
      const resp = await chrome.runtime.sendMessage({ type: "offscreen-ping" });
      if (resp?.ready) {
        settleReady();
        return;
      }
    } catch (_) {
      // ignored — fall through to wait
    }
  } else if (!creating) {
    creating = chrome.offscreen
      .createDocument({
        url: OFFSCREEN_URL,
        reasons: ["AUDIO_PLAYBACK"],
        justification: "Persistent media playback when the popup is closed.",
      })
      .catch((e) => {
        if (!String(e).includes("Only a single offscreen document")) throw e;
      })
      .finally(() => {
        creating = null;
      });
  }
  if (creating) {
    try {
      await creating;
    } catch (e) {
      throw e;
    }
  }

  // Wait for the explicit ready signal or a short timeout as a backstop.
  if (offscreenReady) return;
  await new Promise((resolve) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      resolve();
    };
    readyWaiters.push(finish);
    setTimeout(() => {
      // Last-ditch ping in case we missed the broadcast.
      chrome.runtime
        .sendMessage({ type: "offscreen-ping" })
        .then((resp) => {
          if (resp?.ready) settleReady();
          finish();
        })
        .catch(() => finish());
    }, 800);
    setTimeout(finish, 3000); // hard cap
  });
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg) return;

  if (msg.type === "offscreen-ready") {
    settleReady();
    return; // no response expected
  }

  if (msg.type === "ensure-audio") {
    ensureOffscreen()
      .then(() => sendResponse({ ok: true }))
      .catch((e) => sendResponse({ ok: false, error: String(e) }));
    return true;
  }

  if (msg.type === "audio-cmd") {
    (async () => {
      try {
        await ensureOffscreen();
        const resp = await chrome.runtime.sendMessage({ ...msg, type: "audio-cmd-fwd" });
        sendResponse(resp);
      } catch (e) {
        sendResponse({ error: String(e) });
      }
    })();
    return true;
  }
});
