# Plan

Goal: make YTD_DJ safe and reliable for people who install it from GitHub.

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

## Phase 3: release and docs

- `scripts/release.sh X.Y.Z` bumps `VERSION`, `extension/manifest.json`, and `helper/main.py`, commits, and tags.
- GitHub Action on tag: zips `extension/` and attaches it to a GitHub Release.
- README rewrite: providers, settings page, DB endpoints, security note, development section.
- `CONTRIBUTING.md`: how to run tests and lint.

## Later

- Split `helper/main.py` (1449 lines) into modules.
- Download job queue with progress and retry.

## Decisions

- Audience: people who clone the repo from GitHub. No Chrome Web Store listing.
- macOS is the primary platform. Linux must not break where the fix is small.
- The version lives in three files. CI fails when they disagree.
