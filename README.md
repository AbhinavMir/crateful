# YTD_DJ

Download YouTube audio as MP3 (or video as MP4) into AI-categorized folders, then browse and play the library inside Chrome. Built for personal DJ practice with royalty-free content. Audio lands in `~/YTD_DJ/{genre}/{sub-genre}/` with ID3 tags, so Djay Pro or any tag-aware player can filter by genre. Video lands in `~/YTD_DJ_Video/`, a separate root, so a music-only library tool does not index it.

> Personal-use tool. Do not use it to redistribute or perform copyrighted content. You are responsible for YouTube's Terms of Service and for copyright.

## What you get

- A Chrome extension that adds **Download MP3** and **Download Video** buttons to YouTube watch pages.
- A local Python helper (FastAPI) that runs yt-dlp and ffmpeg, asks an AI model to categorize each download, writes ID3 tags, and saves the file.
- A file-explorer page with folder navigation, playback with resume, rename, move, delete, re-categorize, and reveal in Finder.
- A popup player that keeps playing after you close the popup.

Everything runs on your machine. Nothing is hosted. You supply your own API key, or run a local model with Ollama for no key and no cost.

## Requirements

- Python 3.10 or newer
- ffmpeg (`brew install ffmpeg`, or `sudo apt install ffmpeg`)
- Google Chrome
- One of: an Anthropic API key, an OpenAI API key, or Ollama running locally

macOS is the primary platform. The helper and extension work on Linux. The background-service script is macOS only.

## Install

```bash
git clone https://github.com/AbhinavMir/downloadsounds.git ytd_dj
cd ytd_dj
./install.sh
```

`install.sh` checks your dependencies, creates `helper/.venv`, installs the Python packages, and on macOS installs the helper as a LaunchAgent that starts at login and restarts on crash. Pass `--no-service` to skip the LaunchAgent and start the helper yourself with `helper/run.sh`. Running `install.sh` again is safe.

Then load the extension:

1. Open `chrome://extensions`.
2. Turn on **Developer mode**.
3. Click **Load unpacked** and pick the `extension/` folder.
4. Pin **YTD DJ** to the toolbar.

Then add your API key: click the YTD DJ icon, open **Settings**, pick a provider, paste the key, and click **Test**. Keys are written to `~/.ytd_dj/config.json`. You can also export `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` in the shell that starts the helper.

## Use it

1. Open a YouTube video.
2. Click **Download MP3** or **Download Video** next to the Like button.
3. The helper downloads the media, asks the model for a folder from the title, description, tags, and your existing folders, writes ID3 tags, and saves the file.
4. Click the extension icon for the popup library, or **Open browser** for the full file explorer.

Files are saved as:

- `~/YTD_DJ/{genre}/{sub-genre}/{Artist - Title}.mp3`
- `~/YTD_DJ_Video/{genre}/{sub-genre}/{Artist - Title}.mp4`

The dropdown next to the download buttons overrides the model for one download. Use a cheap model for obvious tracks and a strong one when the metadata is thin.

## How it works

```
┌────────────────────────┐         ┌──────────────────────────┐
│  Chrome extension      │  POST   │  Local helper (FastAPI)  │
│  - YouTube buttons     │ ──────► │  127.0.0.1:7531          │
│  - popup + player      │         │  - yt-dlp → ffmpeg → mp3 │
│  - file browser        │ ◄────── │  - AI categorize         │
│  - settings            │  JSON   │  - mutagen ID3 tags      │
└────────────────────────┘         │  - SQLite playback state │
                                   └──────────────────────────┘
                                              │
                                              ▼
                                   ~/YTD_DJ/{genre}/{sub}/track.mp3
                                   ~/YTD_DJ_Video/{genre}/{sub}/track.mp4
```

For each download the helper sends the title, channel, duration, tags, categories, the first 2000 characters of the description, and your current folder list to the model. The model returns `{content_type, top_folder, sub_folder, artist, title, id3_genre}`. It prefers existing folders, so the library does not fragment. Podcasts go to `podcasts/{show}`, talks to `spoken/{topic}`, sound effects to `other/{bucket}`, and music to `{genre}/{sub-genre}`.

Playback state lives in SQLite at `~/.ytd_dj/library.db`. It records position, completion, play count, and per-file metadata, which drives resume and the continue-listening list.

## AI providers

| Provider | Default model | Needs a key | Notes |
| --- | --- | --- | --- |
| Anthropic | `claude-sonnet-4-6` | yes | Default. Prompt caching keeps the cost low. |
| OpenAI | `gpt-4o` | yes | Uses JSON mode. |
| Ollama | `llama3.1:8b` | no | Local and free. Run `ollama pull llama3.1:8b` first. |

Change the provider, the model, and the categorization prompt on the Settings page. Edit the prompt if the model keeps choosing folders you do not want.

## Security

The helper listens on `127.0.0.1` only, so nothing outside your machine can reach it. It also checks the `Origin` header: only the extension (`chrome-extension://...`) and `https://www.youtube.com` are accepted. Any other web page that tries to reach `127.0.0.1:7531` gets a 403, so a page you visit cannot delete your files or read your config. Requests with no `Origin` header, such as curl, are treated as local tools and allowed.

Your API keys stay in `~/.ytd_dj/config.json`. `GET /config` reports whether a key is set, never the key itself.

## Updating

The popup shows a banner when `VERSION` on `main` is ahead of your installed extension. Click **Update**. The helper runs `git pull`, installs any new Python packages, upgrades yt-dlp, and restarts itself. Reload the extension on `chrome://extensions` afterwards to pick up new extension files.

YouTube changes break older yt-dlp releases regularly. When a download fails with a yt-dlp error, open **Settings** and click **Update yt-dlp**. The helper upgrades the package and restarts.

## Background service (macOS)

```bash
cd helper
./service.sh install     # start now and at login
./service.sh status      # running state and recent log lines
./service.sh log         # follow the log
./service.sh restart     # after editing main.py
./service.sh uninstall   # remove the service
```

Logs go to `~/.ytd_dj/helper.log`.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/status` | health, dependency check, versions |
| GET, PUT | `/config` | read and write settings |
| POST | `/test-key` | check a provider key or the Ollama URL |
| POST | `/download` | `{url, kind: audio\|video, model?}` |
| GET | `/check?url=` | is this video already downloaded |
| GET | `/library?root=` | flat list of every file |
| GET | `/browse?root=&path=` | one folder, with playback state |
| GET | `/folders?root=` | every folder, for move pickers |
| GET | `/file?root=&path=` | stream a file |
| DELETE | `/file?root=&path=` | delete a file |
| POST | `/file/rename` | rename in place |
| POST | `/file/move` | move to another folder |
| POST | `/file/reclassify` | ask the model again and move |
| POST | `/folder/create` | create a folder |
| POST | `/reveal?root=&path=` | show in Finder or the file manager |
| GET | `/db/file?root=&path=` | metadata and playback state |
| POST | `/db/position` | save a playback position |
| POST | `/db/completed` | mark played or unplayed |
| GET | `/db/continue?root=` | continue-listening list |
| POST | `/db/backfill` | add files found on disk to the database |
| GET | `/version` | installed and latest version |
| POST | `/update` | git pull, refresh deps, restart |
| POST | `/update/yt-dlp` | upgrade yt-dlp and restart |

Every `path` parameter is resolved against the configured root, so a path cannot escape the library.

## Configuration

| Setting | Where | Default |
| --- | --- | --- |
| Audio root | Settings page, or `audio_root` | `~/YTD_DJ` |
| Video root | Settings page, or `video_root` | `~/YTD_DJ_Video` |
| Provider and model | Settings page | Anthropic, `claude-sonnet-4-6` |
| API keys | Settings page, or env vars | none |
| Categorization prompt | Settings page | built-in prompt |
| Config directory | `YTD_DJ_HOME` env var | `~/.ytd_dj` |
| Port | `YTD_DJ_PORT` env var | 7531 |

Changing the port also means editing `HELPER` in `extension/content.js`, `popup.js`, `library.js`, `settings.js`, and `offscreen.js`, plus `host_permissions` in `extension/manifest.json`.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| "Helper not running" | Run `./install.sh`, or `helper/service.sh status`. |
| "no API key" | Add a key on the Settings page and click Test. |
| "ffmpeg missing" | `brew install ffmpeg`, then restart the helper. |
| Download fails with a yt-dlp error | Settings, then **Update yt-dlp**. |
| No buttons on YouTube | YouTube renamed its DOM. Adjust `findAnchor()` in `extension/content.js`. |
| Helper stops after a Homebrew Python upgrade | `helper/run.sh` rebuilds the venv by itself. Run `helper/service.sh restart`. |
| Files on disk are missing from the library | `curl -X POST http://127.0.0.1:7531/db/backfill` |

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md). In short:

```bash
cd helper
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check .
.venv/bin/pytest
```

## Limitations

- Single user, no authentication. The helper trusts anything running on your machine.
- Categorization is only as good as the YouTube metadata. Fix folders by hand, or use **Re-categorize** after editing the prompt.
- Each download costs one AI request. Ollama makes that free.
- Downloads run one at a time and block until finished. There is no queue.

## License

MIT. See `LICENSE`.
