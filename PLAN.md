# Plan

Goal: make Crateful safe and reliable for people who install it from GitHub.

## Phase 1: harden the helper (branch `harden-helper`)

- Origin allowlist. Only `chrome-extension://*` and `https://www.youtube.com` can call the helper from a browser. Other sites get 403.
- `YTD_DJ_HOME` env var moves the config/state directory. Tests use it to stay out of the real library.
- Test suite: 69 pytest tests in `helper/tests/`. yt-dlp and the AI call are faked.
- Lint: ruff, config in `helper/pyproject.toml`.
- CI: GitHub Actions runs ruff, pytest (Python 3.10 and 3.13), and `scripts/check_version.sh`.

## Phase 2: install and update

- `install.sh` at repo root: checks python3 and ffmpeg, creates the venv, installs the LaunchAgent, prints the extension steps.
- `run.sh` reinstalls deps when `requirements.txt` changes.
- `/update` runs `git pull`, then `pip install -r requirements.txt`, then `pip install -U yt-dlp`, then re-execs itself. This works with or without the LaunchAgent.
- `/reveal` uses `xdg-open` on Linux.
- Extension shows a clear message when yt-dlp fails and points at the update button.

## Phase 3: release and docs (done)

- `scripts/release.sh X.Y.Z [--push]` bumps `VERSION`, `extension/manifest.json`, and `helper/main.py`, commits, and tags.
- `.github/workflows/release.yml` runs on a `v*` tag. It checks that the tag matches `VERSION`, then creates the GitHub Release with generated notes.
- README rewritten: providers, settings, security, updating, full endpoint table, troubleshooting.
- `CONTRIBUTING.md` covers setup, checks, the Chrome reload loop, and the release command.

## Phase 4: one-button download (done)

- The YouTube row now shows one **Download** button plus a **⋮** menu. Download alone takes the audio and lets the AI file it.
- The menu lists recent folders first, then all folders, with a filter box, an audio/video switch, and an offer to create a folder that does not exist yet. Picking a folder sends `folder` to `/download`, which skips the model entirely.
- `/folders` also returns recent folders. New `/path-presets` feeds one-click library destinations on the Settings page.
- The categorization prompt was rewritten: a fixed genre vocabulary, hard anti-fragmentation rules, remix and featured-artist handling, a low-confidence path to `unsorted/general`, and BPM and key extraction written to the ID3 TBPM and TKEY tags.
- The per-download model dropdown is gone from the page. The `model` field still works over the API.

## Later

- Split `helper/main.py` (1449 lines) into modules.
- Download job queue with progress and retry.

## Decisions

- Audience: people who clone the repo from GitHub. No Chrome Web Store listing.
- macOS is the primary platform. Linux must not break where the fix is small.
- The version lives in three files. CI fails when they disagree.
