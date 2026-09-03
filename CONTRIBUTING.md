# Contributing

## Set up

```bash
./install.sh --no-service
cd helper
.venv/bin/pip install -r requirements-dev.txt
```

## Check your change

```bash
cd helper
.venv/bin/ruff check .
.venv/bin/pytest
../scripts/check_version.sh
```

CI runs the same three commands on every pull request, on Python 3.10 and 3.13.

The tests fake yt-dlp and the AI call. They never touch the network, `~/.ytd_dj`, or your library. `YTD_DJ_HOME` points them at a temporary directory.

## Try it in Chrome

- Extension pages (`popup.html`, `library.html`, `settings.html`) load from disk each time you open them.
- After you edit `content.js`, `background.js`, or `manifest.json`, click the reload icon for YTD DJ on `chrome://extensions`.
- After you edit `helper/main.py`, run `helper/service.sh restart`, or stop and start `helper/run.sh`.

## Open a pull request

- One change per branch. Name the branch after the change, for example `fix-rename-conflict`.
- The pull request body says what changed and how you checked it.
- Do not bump the version in a feature branch. Releases are separate commits, see below.

## Release

```bash
scripts/release.sh 0.12.0 --push
```

This writes the version to `VERSION`, `extension/manifest.json`, and `helper/main.py`, commits, tags `v0.12.0`, and pushes. The tag triggers the Release workflow, which creates the GitHub Release with generated notes. The in-app updater compares the extension version with `VERSION` on `main`, so the bump must be on `main` before users see it.
