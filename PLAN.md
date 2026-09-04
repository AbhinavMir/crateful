# Plan

Crateful: a Chrome extension plus a local Python helper that downloads YouTube
audio into AI-categorized folders.

## Shape

- `helper/main.py` is the whole backend. FastAPI on 127.0.0.1:7531.
- `extension/` is plain JavaScript, no build step.
- The version lives in `VERSION`, `extension/manifest.json`, and `helper/main.py`.
  CI fails when they disagree.
- No tests. Keep it simple and verify by running it.

## Done

- Origin allowlist: only the extension and www.youtube.com can call the helper.
- `install.sh`, self-restarting updater, `scripts/release.sh`, GitHub Releases on tag.
- One Download button with a folder menu, recent folders, and folder creation.
- Playlists: `/playlist` lists entries, each downloads and is filed on its own,
  already-saved entries are skipped, and a run can be stopped.
- URLs are reduced to `watch?v=ID`, so `&list=` no longer pulls a whole playlist.
- Force re-download replaces the previous file for that video.
- Customisable button: label, colours, corner radius, crate icon.
- `cookies_from_browser` for when YouTube asks for sign-in verification.
- Provider failures return 502 with a readable message, and unhandled errors
  return JSON that still carries CORS headers.

## Later

- Split `helper/main.py` if it gets unwieldy.
- A download queue with progress, instead of one blocking request at a time.
