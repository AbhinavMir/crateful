# Crateful

<img src="extension/icons/icon-128.png" alt="" width="96" align="right">

Download YouTube audio as MP3 (or video as MP4) into AI-categorized folders, then browse and play the library inside Chrome. Built for personal DJ practice with royalty-free content. Audio lands in `~/YTD_DJ/{genre}/{sub-genre}/` with ID3 tags, so Djay Pro or any tag-aware player can filter by genre. Video lands in `~/YTD_DJ_Video/`, a separate root, so a music-only library tool does not index it.

> Personal-use tool. Do not use it to redistribute or perform copyrighted content. You are responsible for YouTube's Terms of Service and for copyright.

## What you get

- A Chrome extension that adds one **Download** button to YouTube watch pages, with a **⋮** menu for picking a folder yourself, grabbing the video, taking a whole playlist, or downloading again.
- A local Python helper (FastAPI) that runs yt-dlp and ffmpeg, asks an AI model to file each download, writes ID3 tags, and saves the file.
- A file-explorer page with folder navigation, playback with resume, rename, move, delete, re-categorize, and reveal in Finder.
- A popup player that keeps playing after you close the popup.

Everything runs on your machine. Nothing is hosted. An API key is optional: without one, downloads still work and land in `unsorted/general`.

## Requirements

- Python 3.10 or newer
- ffmpeg (`brew install ffmpeg`, or `sudo apt install ffmpeg`)
- Google Chrome
- Optionally, for AI filing: an Anthropic API key, an OpenAI API key, or Ollama running locally

macOS is the primary platform. The helper and extension work on Linux. The background-service script is macOS only.

## Install

```bash
git clone https://github.com/AbhinavMir/crateful.git crateful
cd crateful
./install.sh
```

`install.sh` checks your dependencies, creates `helper/.venv`, installs the Python packages, and on macOS installs the helper as a LaunchAgent that starts at login and restarts on crash. Pass `--no-service` to skip the LaunchAgent and start the helper yourself with `helper/run.sh`. Running `install.sh` again is safe.

Then load the extension:

1. Open `chrome://extensions`.
2. Turn on **Developer mode**.
3. Click **Load unpacked** and pick the `extension/` folder.
4. Pin **Crateful** to the toolbar.

### AI filing is optional

Without a working key the tool still downloads. Files land in `unsorted/general`, named from the video's own metadata. The button says "Saved → unsorted/general (no AI)". The same happens if the provider rejects the key, rate limits you, or is down: nothing fails, the track just lands unsorted.

Add a key later and use **Re-categorize** in the file browser to file those tracks properly.

To add one: click the Crateful icon, open **Settings**, pick a provider, paste the key, and click **Test**. Keys are written to `~/.ytd_dj/config.json`. You can also export `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` in the shell that starts the helper.

## Use it

1. Open a YouTube video.
2. Click **Download** next to the Like button. That grabs the audio and lets the AI file it.
3. Click the **⋮** next to it when you want to choose. The menu lists your recent folders first, then all of them, with a filter box. Pick one and the track goes straight there with no AI call, so it costs nothing and returns faster. Switch to the **Video** tab in the same menu to download the video instead.
4. Type a folder that does not exist yet and the menu offers to create it.
5. Click the extension icon for the popup library, or **Open browser** for the full file explorer.

Once a video is downloaded the button turns green. Click it to show the file in Finder. The **⋮** menu then also lists where the file went, with **Open in Finder**, and a **Download again** that replaces the old file rather than leaving a second copy beside it.

### Playlists

The button also appears on a playlist page, next to Play all, reading **Download 41** or however many the playlist holds. Each video is downloaded and filed on its own, exactly as a single download would be, so a playlist of mixed genres spreads across the folders it belongs in rather than landing in one heap.

Videos already in your library are skipped, so re-running a playlist resumes rather than starting over. The menu also offers a run that skips nothing. Click the button while a run is going to stop it after the current track. The **⋮** menu can send the whole playlist to one folder instead of letting the AI file each track.

The same options appear on a watch page opened from a playlist, and on a Mix. A Mix is the endless radio YouTube builds around a track, so the menu offers its first 50 entries and says so.

The button's look is yours: **Settings** has a label field, background, text and border colours, a corner-radius slider, and a toggle for the crate icon, with four presets to start from. Saving updates every open YouTube tab straight away.

Files are saved as:

- `~/YTD_DJ/{genre}/{sub-genre}/{Artist - Title}.mp3`
- `~/YTD_DJ_Video/{genre}/{sub-genre}/{Artist - Title}.mp4`

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

For each download the helper sends the title, channel, duration, tags, categories, the first 2000 characters of the description, and your current folder list to the model. The model returns `{content_type, top_folder, sub_folder, artist, title, id3_genre, bpm, musical_key, confidence}`. Podcasts go to `podcasts/{show}`, talks to `spoken/{topic}`, sound effects to `other/{bucket}`, and music to `{genre}/{sub-genre}`.

The prompt works hard against a fragmented library. The model gets your exact folder list and is told to reuse a folder rather than coin a near-duplicate, so `deep-house` and `deephouse` never end up side by side. It picks a top folder from a fixed genre vocabulary, keeps remix and edit credits in the title while stripping "(Official Video)" and its relatives, credits the original artist rather than the remixer, and drops featured guests. When the metadata is too thin to place a track it returns low confidence and the track lands in `unsorted/general` instead of a wrong genre, because a wrong folder costs more than an unsorted one.

BPM and musical key are read out of the title or description when they are stated outright, never guessed, and written to the ID3 `TBPM` and `TKEY` tags that Djay Pro and Rekordbox read.

Every link is reduced to `https://www.youtube.com/watch?v=ID` before yt-dlp sees it. This matters most for `&list=`: yt-dlp reads that as a playlist, names the file after the playlist, and downloads every entry. `&t=`, `&index=`, `&pp=` and `&si=` are merely noise. A playlist is downloaded only when you ask for it in the menu.

Picking a folder from the **⋮** menu skips the model completely. Artist and title then come from the video metadata: yt-dlp's own music tags when the channel provides them, otherwise the title split on its dash with the usual upload noise stripped.

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
| POST | `/download` | `{url, kind: audio\|video, model?, folder?, force?}` |
| GET | `/playlist?url=` | list a playlist's videos, without downloading |
| POST | `/check-bulk` | which of these video ids are already saved |
| GET | `/check?url=` | is this video already downloaded |
| GET | `/library?root=` | flat list of every file |
| GET | `/browse?root=&path=` | one folder, with playback state |
| GET | `/folders?root=` | every folder plus recent ones, for pickers |
| GET | `/path-presets` | common library destinations |
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
| Cookies from browser | Settings page, or `cookies_from_browser` | off |
| Config directory | `YTD_DJ_HOME` env var | `~/.ytd_dj` |
| Port | `YTD_DJ_PORT` env var | 7531 |

The Settings page has one-click destinations for the library root: Desktop, Downloads, Music, Documents, or your home folder. Pick one and both roots move together. Existing files stay where they are, so move them yourself if you want them to follow.

Changing the port also means editing `HELPER` in `extension/content.js`, `popup.js`, `library.js`, `settings.js`, and `offscreen.js`, plus `host_permissions` in `extension/manifest.json`.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| "Helper not running" | Run `./install.sh`, or `helper/service.sh status`. |
| Everything lands in `unsorted/general` | No working AI key. Add one in Settings, or leave it and file by hand. |
| "ffmpeg missing" | `brew install ffmpeg`, then restart the helper. |
| Download fails with a yt-dlp error | Settings, then **Update yt-dlp**. |
| "YouTube wants sign-in verification" | Set **Use cookies from browser** in Settings to a browser you are signed into YouTube with. YouTube throttles a machine that makes many requests, which a playlist run can trigger. |
| No buttons on YouTube | YouTube renamed its DOM. Adjust `findAnchor()` in `extension/content.js`. |
| Helper stops after a Homebrew Python upgrade | `helper/run.sh` rebuilds the venv by itself. Run `helper/service.sh restart`. |
| Files on disk are missing from the library | `curl -X POST http://127.0.0.1:7531/db/backfill` |

## Development

The helper is one file, `helper/main.py`. The extension is plain JavaScript in `extension/`, no build step.

- After editing `helper/main.py`, run `helper/service.sh restart`.
- After editing `content.js`, `background.js`, or `manifest.json`, reload the extension on `chrome://extensions`.
- Extension pages reload themselves each time you open them.

Cut a release with `scripts/release.sh 0.16.0 --push`, which bumps the version in all three files, tags it, and lets the workflow publish the GitHub Release.

## Limitations

- Single user, no authentication. The helper trusts anything running on your machine.
- Categorization is only as good as the YouTube metadata. Fix folders by hand, or use **Re-categorize** after editing the prompt.
- Each download costs one AI request. Ollama makes that free.
- Downloads run one at a time and block until finished. There is no queue, so a large playlist holds the button for its whole run.
- A long playlist run can trip YouTube's bot check. Cookies from a signed-in browser are the fix, and the setting only helps if that browser is actually signed in.
- Picking a folder yourself skips the model, so the artist and title come from a plain text split of the video title. Expect the AI path to name files better.

## License

MIT. See `LICENSE`.
