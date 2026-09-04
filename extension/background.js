self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

const OFFSCREEN_URL = "offscreen.html";

const WATCH_MATCH = "*://www.youtube.com/watch*";

async function hasLiveContentScript(tabId) {
  try {
    const resp = await chrome.tabs.sendMessage(tabId, { type: "crateful-ping" });
    return resp?.alive === true;
  } catch (_) {
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
      console.warn("[Crateful] re-inject failed for tab", tab.id, e);
    }
  }
}

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
  if (offscreenReady) return;

  let hasDoc = false;
  try {
    hasDoc = !!(await chrome.offscreen.hasDocument?.());
  } catch (_) {}

  if (hasDoc) {
    try {
      const resp = await chrome.runtime.sendMessage({ type: "offscreen-ping" });
      if (resp?.ready) {
        settleReady();
        return;
      }
    } catch (_) {
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
      chrome.runtime
        .sendMessage({ type: "offscreen-ping" })
        .then((resp) => {
          if (resp?.ready) settleReady();
          finish();
        })
        .catch(() => finish());
    }, 800);
    setTimeout(finish, 3000);
  });
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg) return;

  if (msg.type === "offscreen-ready") {
    settleReady();
    return;
  }

  if (msg.type === "open-settings") {
    chrome.tabs.create({ url: chrome.runtime.getURL("settings.html") });
    return;
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
