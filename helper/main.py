import importlib.metadata
import json
import os
import platform
import re
import shutil
import sqlite3
import ssl
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from contextlib import closing
from pathlib import Path

import certifi
import yt_dlp
from anthropic import Anthropic
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from mutagen.id3 import ID3, TALB, TBPM, TCON, TDRC, TIT2, TKEY, TPE1
from mutagen.mp3 import MP3
from pydantic import BaseModel

DEFAULT_AUDIO_DIR = Path.home() / "YTD_DJ"
DEFAULT_VIDEO_DIR = Path.home() / "YTD_DJ_Video"

CONFIG_DIR = Path(os.environ.get("YTD_DJ_HOME") or (Path.home() / ".ytd_dj")).expanduser()
CONFIG_FILE = CONFIG_DIR / "config.json"
HISTORY_FILE = CONFIG_DIR / "history.json"
DB_FILE = CONFIG_DIR / "library.db"
PORT = int(os.environ.get("YTD_DJ_PORT") or 7531)
VERSION = "0.17.0"

DEFAULT_PROVIDER = "anthropic"
DEFAULT_MODEL_BY_PROVIDER = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4o",
    "ollama": "llama3.1:8b",
}
SUPPORTED_PROVIDERS = set(DEFAULT_MODEL_BY_PROVIDER.keys())
DEFAULT_OLLAMA_URL = "http://localhost:11434"


SUPPORTED_COOKIE_BROWSERS = {"chrome", "chromium", "brave", "edge", "firefox", "safari", "opera", "vivaldi"}
REPO = "AbhinavMir/crateful"
REMOTE_VERSION_URL = f"https://raw.githubusercontent.com/{REPO}/main/VERSION"


SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

YOUTUBE_ID_RE = re.compile(
    r"(?:youtu\.be/|youtube\.com/(?:watch\?(?:.*&)?v=|embed/|shorts/|v/))([A-Za-z0-9_-]{11})"
)


YDL_BASE_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "noplaylist": True,
}

CONFIG_DIR.mkdir(parents=True, exist_ok=True)


ALLOWED_ORIGIN_PATTERN = r"^(chrome-extension://[a-p]{32}|https://www\.youtube\.com)$"
ALLOWED_ORIGIN_RE = re.compile(ALLOWED_ORIGIN_PATTERN)


class OriginAllowlistMiddleware:
    def __init__(self, app, pattern: re.Pattern):
        self.app = app
        self.pattern = pattern

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            origin = None
            for name, value in scope.get("headers", []):
                if name == b"origin":
                    origin = value.decode("latin-1")
                    break
            if origin is not None and not self.pattern.match(origin):
                response = JSONResponse({"detail": "Origin not allowed"}, status_code=403)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


class ErrorEnvelopeMiddleware:

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def send_wrapper(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as e:
            traceback.print_exc()
            if started:
                raise
            response = JSONResponse(
                {"detail": f"Helper error: {type(e).__name__}: {e}"[:400]},
                status_code=500,
            )
            await response(scope, receive, send)


app = FastAPI(title="YTD_DJ Helper")


app.add_middleware(ErrorEnvelopeMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=ALLOWED_ORIGIN_PATTERN,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(OriginAllowlistMiddleware, pattern=ALLOWED_ORIGIN_RE)


class DownloadRequest(BaseModel):
    url: str
    kind: str = "audio"
    model: str | None = None
    folder: str | None = None
    force: bool = False


class ConfigUpdate(BaseModel):
    audio_root: str | None = None
    video_root: str | None = None
    provider: str | None = None
    model: str | None = None
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    ollama_url: str | None = None
    categorize_prompt: str | None = None
    cookies_from_browser: str | None = None


class TestKeyRequest(BaseModel):
    provider: str
    key: str | None = None
    url: str | None = None


class PositionUpdate(BaseModel):
    root: str
    path: str
    position_sec: float
    duration_sec: float | None = None


class CompletedUpdate(BaseModel):
    root: str
    path: str
    completed: bool = True


class RenameRequest(BaseModel):
    root: str
    old_path: str
    new_name: str


class MoveRequest(BaseModel):
    root: str
    old_path: str
    new_dir: str


class CreateFolderRequest(BaseModel):
    root: str
    path: str


class BulkCheckRequest(BaseModel):
    video_ids: list[str]


class ReclassifyRequest(BaseModel):
    root: str
    path: str


def _parse_config_file() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        text = CONFIG_FILE.read_text().strip()
    except OSError:
        return {}
    if not text:
        return {}
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def read_config() -> dict:
    raw = _parse_config_file()

    def pick(*keys):
        for k in keys:
            if raw.get(k):
                return raw[k]
        return None

    provider = (pick("provider", "PROVIDER") or DEFAULT_PROVIDER).lower()
    if provider not in SUPPORTED_PROVIDERS:
        provider = DEFAULT_PROVIDER

    model = pick("model", "MODEL", f"{provider}_model")
    anthropic_key = pick("anthropic_api_key", "ANTHROPIC_API_KEY")
    openai_key = pick("openai_api_key", "OPENAI_API_KEY")
    ollama_url = pick("ollama_url", "OLLAMA_URL") or DEFAULT_OLLAMA_URL
    cookies_browser = (pick("cookies_from_browser", "COOKIES_FROM_BROWSER") or "").lower().strip()
    if cookies_browser not in SUPPORTED_COOKIE_BROWSERS:
        cookies_browser = ""


    if os.environ.get("ANTHROPIC_API_KEY"):
        anthropic_key = os.environ["ANTHROPIC_API_KEY"]
    if os.environ.get("OPENAI_API_KEY"):
        openai_key = os.environ["OPENAI_API_KEY"]
    if os.environ.get("OLLAMA_URL"):
        ollama_url = os.environ["OLLAMA_URL"]
    if os.environ.get("YTD_PROVIDER"):
        env_provider = os.environ["YTD_PROVIDER"].lower()
        if env_provider in SUPPORTED_PROVIDERS:
            provider = env_provider
    if os.environ.get("YTD_MODEL"):
        model = os.environ["YTD_MODEL"]

    if not model:
        model = DEFAULT_MODEL_BY_PROVIDER[provider]

    return {
        "provider": provider,
        "model": model,
        "anthropic_api_key": anthropic_key,
        "openai_api_key": openai_key,
        "ollama_url": ollama_url,
        "cookies_from_browser": cookies_browser,
    }


def active_api_key(cfg: dict | None = None) -> str | None:
    cfg = cfg or read_config()
    if cfg["provider"] == "openai":
        return cfg["openai_api_key"]
    if cfg["provider"] == "anthropic":
        return cfg["anthropic_api_key"]
    return None


def audio_root() -> Path:
    raw = _parse_config_file()
    path = raw.get("audio_root") or raw.get("AUDIO_ROOT")
    p = Path(path).expanduser() if path else DEFAULT_AUDIO_DIR
    p.mkdir(parents=True, exist_ok=True)
    return p


def video_root() -> Path:
    raw = _parse_config_file()
    path = raw.get("video_root") or raw.get("VIDEO_ROOT")
    p = Path(path).expanduser() if path else DEFAULT_VIDEO_DIR
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_roots() -> dict:
    return {"audio": audio_root(), "video": video_root()}


def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_FILE), check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    root TEXT NOT NULL,
    rel_path TEXT NOT NULL,
    source_url TEXT,
    video_id TEXT,
    title TEXT,
    artist TEXT,
    content_type TEXT,
    duration_sec REAL,
    added_at INTEGER NOT NULL,
    UNIQUE(root, rel_path)
);

CREATE TABLE IF NOT EXISTS playback (
    file_id INTEGER PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
    position_sec REAL DEFAULT 0,
    completed INTEGER DEFAULT 0,
    last_played_at INTEGER,
    play_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tags (
    file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    PRIMARY KEY (file_id, tag)
);

CREATE INDEX IF NOT EXISTS idx_files_video_id ON files(video_id);
CREATE INDEX IF NOT EXISTS idx_playback_last_played
    ON playback(last_played_at DESC);
"""


def db_init() -> None:
    with closing(db_connect()) as conn:
        conn.executescript(DB_SCHEMA)
        conn.commit()


def db_upsert_file(
    root: str,
    rel_path: str,
    *,
    source_url: str | None = None,
    video_id: str | None = None,
    title: str | None = None,
    artist: str | None = None,
    content_type: str | None = None,
    duration_sec: float | None = None,
) -> int:
    with closing(db_connect()) as conn:
        conn.execute(
            """
            INSERT INTO files
              (root, rel_path, source_url, video_id, title, artist,
               content_type, duration_sec, added_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(root, rel_path) DO UPDATE SET
              source_url   = COALESCE(excluded.source_url, files.source_url),
              video_id     = COALESCE(excluded.video_id, files.video_id),
              title        = COALESCE(excluded.title, files.title),
              artist       = COALESCE(excluded.artist, files.artist),
              content_type = COALESCE(excluded.content_type, files.content_type),
              duration_sec = COALESCE(excluded.duration_sec, files.duration_sec)
            """,
            (root, rel_path, source_url, video_id, title, artist,
             content_type, duration_sec, int(time.time())),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id FROM files WHERE root=? AND rel_path=?",
            (root, rel_path),
        ).fetchone()
        return int(row["id"]) if row else 0


def db_get_file(root: str, rel_path: str) -> dict | None:
    with closing(db_connect()) as conn:
        f = conn.execute(
            "SELECT * FROM files WHERE root=? AND rel_path=?",
            (root, rel_path),
        ).fetchone()
        if not f:
            return None
        p = conn.execute(
            "SELECT * FROM playback WHERE file_id=?", (f["id"],)
        ).fetchone()
        return {
            "id": f["id"],
            "root": f["root"],
            "rel_path": f["rel_path"],
            "source_url": f["source_url"],
            "video_id": f["video_id"],
            "title": f["title"],
            "artist": f["artist"],
            "content_type": f["content_type"],
            "duration_sec": f["duration_sec"],
            "added_at": f["added_at"],
            "position_sec": (p["position_sec"] if p else 0) or 0,
            "completed": bool(p and p["completed"]),
            "last_played_at": p["last_played_at"] if p else None,
            "play_count": (p["play_count"] if p else 0) or 0,
        }


def _ensure_file_id(conn: sqlite3.Connection, root: str, rel_path: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM files WHERE root=? AND rel_path=?",
        (root, rel_path),
    ).fetchone()
    if row:
        return int(row["id"])
    full = root_for(root) / rel_path
    if not full.exists():
        return None
    conn.execute(
        """
        INSERT INTO files (root, rel_path, added_at)
        VALUES (?, ?, ?)
        ON CONFLICT(root, rel_path) DO NOTHING
        """,
        (root, rel_path, int(time.time())),
    )
    row = conn.execute(
        "SELECT id FROM files WHERE root=? AND rel_path=?",
        (root, rel_path),
    ).fetchone()
    return int(row["id"]) if row else None


def db_update_position(root: str, rel_path: str, position_sec: float,
                       duration_sec: float | None = None) -> None:
    with closing(db_connect()) as conn:
        fid = _ensure_file_id(conn, root, rel_path)
        if fid is None:
            raise HTTPException(404, "File not found")
        if duration_sec:
            conn.execute(
                "UPDATE files SET duration_sec = ? WHERE id = ?",
                (duration_sec, fid),
            )
        now = int(time.time())
        conn.execute(
            """
            INSERT INTO playback (file_id, position_sec, last_played_at, play_count)
            VALUES (?, ?, ?, 0)
            ON CONFLICT(file_id) DO UPDATE SET
              position_sec   = excluded.position_sec,
              last_played_at = excluded.last_played_at
            """,
            (fid, max(0.0, float(position_sec)), now),
        )
        conn.commit()


def db_mark_completed(root: str, rel_path: str, completed: bool = True) -> None:
    with closing(db_connect()) as conn:
        fid = _ensure_file_id(conn, root, rel_path)
        if fid is None:
            raise HTTPException(404, "File not found")
        now = int(time.time())
        if completed:
            conn.execute(
                """
                INSERT INTO playback (file_id, completed, last_played_at, play_count)
                VALUES (?, 1, ?, 1)
                ON CONFLICT(file_id) DO UPDATE SET
                  completed       = 1,
                  last_played_at  = excluded.last_played_at,
                  play_count      = playback.play_count + 1
                """,
                (fid, now),
            )
        else:
            conn.execute(
                "UPDATE playback SET completed = 0 WHERE file_id = ?",
                (fid,),
            )
        conn.commit()


def db_continue_listening(root: str, limit: int = 20) -> list[dict]:
    with closing(db_connect()) as conn:
        rows = conn.execute(
            """
            SELECT f.root, f.rel_path, f.title, f.artist, f.duration_sec,
                   p.position_sec, p.last_played_at
            FROM playback p
            JOIN files f ON p.file_id = f.id
            WHERE p.position_sec > 0 AND p.completed = 0 AND f.root = ?
            ORDER BY p.last_played_at DESC
            LIMIT ?
            """,
            (root, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def db_delete_file(root: str, rel_path: str) -> None:
    with closing(db_connect()) as conn:
        conn.execute(
            "DELETE FROM files WHERE root=? AND rel_path=?",
            (root, rel_path),
        )
        conn.commit()


def db_update_path(root: str, old_rel: str, new_rel: str) -> None:
    with closing(db_connect()) as conn:
        conn.execute(
            "UPDATE files SET rel_path = ? WHERE root = ? AND rel_path = ?",
            (new_rel, root, old_rel),
        )
        conn.commit()


def db_update_content_type(root: str, rel_path: str, content_type: str) -> None:
    with closing(db_connect()) as conn:
        conn.execute(
            "UPDATE files SET content_type = ? WHERE root = ? AND rel_path = ?",
            (content_type, root, rel_path),
        )
        conn.commit()


def history_update_path(root: str, old_rel: str, new_rel: str) -> None:
    hist = read_history()
    changed = False
    for entry in hist.values():
        if entry.get(root) == old_rel:
            entry[root] = new_rel
            changed = True
    if changed:
        write_history(hist)


def db_backfill_from_disk() -> int:
    added = 0
    with closing(db_connect()) as conn:
        existing = {
            (r["root"], r["rel_path"])
            for r in conn.execute("SELECT root, rel_path FROM files").fetchall()
        }
        now = int(time.time())
        for kind, base in get_roots().items():
            pattern = "*.mp3" if kind == "audio" else "*.mp4"
            for f in base.rglob(pattern):
                rel = str(f.relative_to(base))
                if (kind, rel) in existing:
                    continue
                conn.execute(
                    """
                    INSERT INTO files (root, rel_path, added_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(root, rel_path) DO NOTHING
                    """,
                    (kind, rel, now),
                )
                added += 1
        conn.commit()
    return added


def get_categorize_prompt() -> str:
    raw = _parse_config_file()
    override = raw.get("categorize_prompt") or raw.get("CATEGORIZE_PROMPT")
    if override and isinstance(override, str) and override.strip():
        return override
    return CATEGORIZE_SYSTEM


def root_for(kind: str) -> Path:
    roots = get_roots()
    if kind not in roots:
        raise HTTPException(400, f"Invalid kind/root: {kind}")
    return roots[kind]


def safe_path(kind: str, rel: str) -> Path:
    base = root_for(kind).resolve()
    rel = (rel or "").lstrip("/")
    target = (base / rel).resolve()
    if base != target and base not in target.parents:
        raise HTTPException(400, "Path traversal blocked")
    return target


def extract_video_id(url: str) -> str | None:
    if not url:
        return None
    m = YOUTUBE_ID_RE.search(url)
    return m.group(1) if m else None


def ydl_opts(**extra) -> dict:
    opts = {**YDL_BASE_OPTS, **extra}
    browser = read_config().get("cookies_from_browser")
    if browser:
        opts["cookiesfrombrowser"] = (browser,)
    return opts


MIX_LIST_RE = re.compile(r"[?&]list=(RD|UL|OL)[A-Za-z0-9_-]*")


def is_mix_url(url: str) -> bool:
    return bool(MIX_LIST_RE.search(url or ""))


def canonical_url(url: str) -> str:
    vid = extract_video_id(url)
    return f"https://www.youtube.com/watch?v={vid}" if vid else url


def read_history() -> dict:
    if not HISTORY_FILE.exists():
        return {}
    try:
        data = json.loads(HISTORY_FILE.read_text() or "{}")
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def write_history(hist: dict) -> None:
    try:
        HISTORY_FILE.write_text(json.dumps(hist, indent=2))
    except OSError as e:
        print(f"History write failed: {e}", file=sys.stderr)


def record_download(video_id: str | None, kind: str, rel_path: str) -> None:
    if not video_id:
        return
    hist = read_history()
    entry = hist.setdefault(video_id, {})
    entry[kind] = rel_path
    write_history(hist)


def friendly_ydl_error(e: Exception) -> str:
    msg = str(e)
    if "not a bot" in msg or "cookies" in msg.lower():
        return ("YouTube wants sign-in verification from this machine. "
                "Set 'Use cookies from browser' in Settings.")
    return msg


def previous_download_path(kind: str, video_id: str | None) -> Path | None:
    if not video_id:
        return None
    rel = read_history().get(video_id, {}).get(kind)
    if not rel:
        return None
    full = root_for(kind) / rel
    return full if full.is_file() else None


@app.get("/playlist")
def playlist_info(url: str = Query(...), limit: int = Query(50, ge=1, le=500)):
    opts = ydl_opts(
        skip_download=True,
        noplaylist=False,
        extract_flat="in_playlist",
        playlistend=limit,
    )
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        raise HTTPException(400, f"yt-dlp failed: {friendly_ydl_error(e)}") from e

    entries = info.get("entries")
    if not entries:
        return {"is_playlist": False, "is_mix": False, "title": None, "count": 0, "entries": []}

    out = []
    for entry in entries:
        if not entry:
            continue
        vid = entry.get("id")
        if not vid:
            continue
        out.append({
            "video_id": vid,
            "title": entry.get("title") or vid,
            "url": f"https://www.youtube.com/watch?v={vid}",
            "duration_sec": entry.get("duration"),
        })
        if len(out) >= limit:
            break
    return {
        "is_playlist": True,
        "is_mix": is_mix_url(url),
        "title": info.get("title"),
        "count": len(out),
        "truncated": len(out) >= limit,
        "entries": out,
    }


def list_folders(base: Path) -> list[dict]:
    out = []
    for top in sorted(base.iterdir()):
        if not top.is_dir() or top.name.startswith("."):
            continue
        subs = sorted(
            s.name for s in top.iterdir() if s.is_dir() and not s.name.startswith(".")
        )
        out.append({"name": top.name, "subs": subs})
    return out


CATEGORIZE_SYSTEM = """You file YouTube downloads into a working DJ library. Personal practice use only.

You get video metadata and the library's current folder list. Return ONE JSON object. No prose, no code fences.

## The one rule that matters

REUSE AN EXISTING FOLDER. You are given the exact folder list. If a track plausibly belongs in a
folder that already exists, use that folder, spelled exactly as given. A library with 12 good folders
beats one with 60 near-duplicates. Only invent a folder when nothing on the list is a reasonable home.
"deep-house" and "deephouse" and "deep-house-mixes" must never coexist.

## Fields

content_type: "music" | "podcast" | "spoken" | "other"
  music   songs, DJ mixes, live sets, instrumentals, beats, loops, sample packs, remixes
  podcast an episode of a recurring show. Signals: "Ep. 42", "#317", show branding, a regular host
  spoken  one-off talks, lectures, interviews, audiobooks, conference sessions
  other   sound effects, field recordings, foley, risers, drum hits, jingles, tutorials

top_folder: kebab-case.
  music   -> a genre family from this list, unless the library already uses a better one:
          house, techno, trance, dnb, garage, breaks, dubstep, bass, hip-hop, rnb, funk, soul,
          disco, jazz, latin, afro, reggae, dancehall, pop, rock, metal, indie, electronica,
          ambient, lo-fi, experimental, classical, soundtrack, edm
  podcast -> exactly "podcasts"
  spoken  -> exactly "spoken"
  other   -> exactly "other"

sub_folder: kebab-case, more specific.
  music   a sub-genre: deep-house, tech-house, afro-house, melodic-techno, peak-time, liquid-dnb,
          jungle, uk-garage, amapiano, boom-bap, neo-soul, synthwave. Use "general" only when the
          track genuinely has no sub-genre. Prefer a sub_folder that already exists under your
          chosen top_folder.
  podcast the show name: huberman-lab, lex-fridman, dissect
  spoken  a topic or series: philosophy, ai-research, stanford-cs231n
  other   a bucket: risers, impacts, vocal-chops, drum-hits, ambience, foley

artist: who made it, cleaned.
  Titles are usually "Artist - Track". Take the part before the dash.
  Strip channel noise: VEVO, Official, TV, Music, Records, HD, " - Topic".
  Remix -> the ORIGINAL artist is the artist. "Odesza - Line Of Sight (Lane 8 Remix)" -> "Odesza".
  Featured guests are dropped: "Drake feat. Rihanna" -> "Drake".
  Compilation or label upload with no clear artist -> "Various Artists".
  DJ mix or set -> the DJ. "Boiler Room: Peggy Gou" -> "Peggy Gou".
  Nothing usable in the title -> fall back to the cleaned channel name.

title: the track name, cleaned.
  Remove: (Official Video), (Official Audio), (Official Music Video), (Lyric Video), (Visualizer),
  (Audio), [HD], [4K], [Free Download], [NCS Release], "| Free DL", bare genre tags in brackets,
  emoji, and any leading or trailing separators.
  KEEP a remix or edit credit, it identifies the version: "Line Of Sight (Lane 8 Remix)".
  KEEP "Extended Mix", "Radio Edit", "Club Mix", "VIP", "Dub".
  Podcast -> the episode subject, without the show name and episode number prefix.

id3_genre: human-readable, title case. Music -> the real genre, "Deep House", "Drum & Bass",
  "Tech House". Podcast -> "Podcast". Spoken -> "Spoken Word". Other -> "Sound Effects" or "Ambient".

bpm: integer, or null. Only when the title or description states it outright, for example
  "128 BPM" or "(174bpm)". Never guess a tempo from the genre.

musical_key: string, or null. Only when stated. Accept "F# minor", "Fm", or Camelot like "8A".
  Copy it through as written. Never guess.

confidence: "high" | "low".
  Use "low" when the metadata is too thin to place the track with any confidence. On "low" for
  music, set top_folder to "unsorted" and sub_folder to "general" instead of guessing a genre.
  A wrong folder costs more than an unsorted one, because nobody goes back to check.

## Examples

Title "ODESZA - Line Of Sight (Lane 8 Remix) [Official Audio]", channel "ODESZA",
existing folders include house/deep-house:
{"content_type":"music","top_folder":"house","sub_folder":"deep-house","artist":"Odesza",
"title":"Line Of Sight (Lane 8 Remix)","id3_genre":"Deep House","bpm":null,"musical_key":null,
"confidence":"high"}

Title "Peggy Gou | Boiler Room Berlin", 90 minutes, existing folders include house/dj-mixes:
{"content_type":"music","top_folder":"house","sub_folder":"dj-mixes","artist":"Peggy Gou",
"title":"Boiler Room Berlin","id3_genre":"House","bpm":null,"musical_key":null,"confidence":"high"}

Title "Huberman Lab Ep. 84: How to Improve Your Sleep", channel "Andrew Huberman":
{"content_type":"podcast","top_folder":"podcasts","sub_folder":"huberman-lab","artist":"Andrew Huberman",
"title":"How to Improve Your Sleep","id3_genre":"Podcast","bpm":null,"musical_key":null,"confidence":"high"}

Title "untitled_final_2 .wav", channel "user8842", no description:
{"content_type":"music","top_folder":"unsorted","sub_folder":"general","artist":"user8842",
"title":"untitled_final_2","id3_genre":"Unsorted","bpm":null,"musical_key":null,"confidence":"low"}

Respond with ONLY the JSON object."""

CONTENT_TYPES = {"music", "podcast", "spoken", "other"}
FALLBACK_TOP = "unsorted"
FALLBACK_SUB = "general"
FORCED_TOP_BY_TYPE = {"podcast": "podcasts", "spoken": "spoken", "other": "other"}
DEFAULT_ID3_BY_TYPE = {"podcast": "Podcast", "spoken": "Spoken Word"}


def build_categorize_prompt(info: dict, folders: list[dict]) -> str:
    desc = (info.get("description") or "")[:2000]
    tags = info.get("tags") or []
    return (
        f"Title: {info.get('title')}\n"
        f"Channel: {info.get('uploader')}\n"
        f"Duration: {info.get('duration')}s\n"
        f"Tags: {tags[:20]}\n"
        f"Categories: {info.get('categories') or []}\n"
        f"Description (first 2000 chars):\n{desc}\n\n"
        f"Existing folders:\n{json.dumps(folders, indent=2)}"
    )


def _parse_json_response(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def _categorize_anthropic(user_msg: str, model: str, key: str | None) -> dict:
    if not key:
        raise HTTPException(400, "No Anthropic API key set.")
    client = Anthropic(api_key=key)
    resp = client.messages.create(
        model=model,
        max_tokens=500,
        system=[
            {
                "type": "text",
                "text": get_categorize_prompt(),
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_msg}],
    )
    return _parse_json_response(resp.content[0].text)


def _categorize_openai(user_msg: str, model: str, key: str | None) -> dict:
    if not key:
        raise HTTPException(400, "No OpenAI API key set.")
    try:
        from openai import OpenAI
    except ImportError:
        raise HTTPException(500, "openai package not installed. Run: pip install -r helper/requirements.txt") from None
    client = OpenAI(api_key=key)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": get_categorize_prompt()},
            {"role": "user", "content": user_msg},
        ],
        response_format={"type": "json_object"},
        max_completion_tokens=500,
    )
    return _parse_json_response(resp.choices[0].message.content)


def _categorize_ollama(user_msg: str, model: str, base_url: str | None) -> dict:
    url = (base_url or DEFAULT_OLLAMA_URL).rstrip("/") + "/api/chat"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": get_categorize_prompt()},
            {"role": "user", "content": user_msg},
        ],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180, context=SSL_CONTEXT) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8")[:200]
        except Exception:
            pass
        raise HTTPException(500, f"Ollama HTTP {e.code} from {url}: {body or e.reason}") from e
    except urllib.error.URLError as e:
        raise HTTPException(500, f"Ollama unreachable at {url}: {e}") from e
    text = (data.get("message") or {}).get("content") or ""
    if not text.strip():
        raise HTTPException(500, "Ollama returned empty response")
    return _parse_json_response(text)


def categorize(info: dict, folders: list[dict], model_override: str | None = None) -> dict:
    cfg = read_config()
    user_msg = build_categorize_prompt(info, folders)
    model = (model_override or cfg["model"]).strip() if (model_override or cfg["model"]) else cfg["model"]
    try:
        if cfg["provider"] == "openai":
            return _categorize_openai(user_msg, model, cfg["openai_api_key"])
        if cfg["provider"] == "ollama":
            return _categorize_ollama(user_msg, model, cfg["ollama_url"])
        return _categorize_anthropic(user_msg, model, cfg["anthropic_api_key"])
    except HTTPException:
        raise
    except json.JSONDecodeError:
        raise
    except Exception as e:


        raise HTTPException(502, provider_error_message(cfg["provider"], e)) from e


def provider_error_message(provider: str, e: Exception) -> str:
    name = {"anthropic": "Anthropic", "openai": "OpenAI", "ollama": "Ollama"}.get(provider, provider)
    text = str(e)
    status = getattr(e, "status_code", None)
    if status == 401 or "authentication" in text.lower() or "api key" in text.lower():
        return (f"{name} rejected the API key. Check the key in Settings, "
                f"or pick a folder yourself from the menu to download without AI.")
    if status == 429 or "rate limit" in text.lower():
        return f"{name} is rate limiting. Wait, or pick a folder yourself to download without AI."
    if status in (402, 403) or "credit" in text.lower() or "quota" in text.lower():
        return f"{name} refused the request: {text[:160]}"
    return f"{name} call failed: {text[:200]}"


TITLE_NOISE_RE = re.compile(
    r"""\s*[\(\[]\s*(?:
        official\s*(?:music\s*)?(?:video|audio|visualiser|visualizer|lyric\s*video)?
      | lyrics?(?:\s*video)?
      | audio | visuali[sz]er | music\s*video
      | hd | hq | 4k | 8k | \d{3,4}p
      | full\s*(?:album|song)?
      | free\s*(?:download|dl)
      | ncs\s*release
      | out\s*now
    )\s*[\)\]]""",
    re.IGNORECASE | re.VERBOSE,
)
TRAILING_NOISE_RE = re.compile(
    r"\s*\|\s*(?:free\s*(?:download|dl)|out\s*now|official.*)$", re.IGNORECASE
)
CHANNEL_NOISE_RE = re.compile(
    r"\s*(?:-\s*topic|vevo|official|officiel|music|records|recordings|tv|channel)\s*$",
    re.IGNORECASE,
)
BPM_RE = re.compile(r"(?<!\d)(\d{2,3})\s*(?:bpm)\b", re.IGNORECASE)
KEY_RE = re.compile(
    r"\b(?:([A-G][#b\u266f\u266d]?)\s*(?:-|\s)?\s*(minor|major|min|maj|m)\b|(\d{1,2}[AB])\b)"
)


def clean_channel(name: str | None) -> str:
    name = (name or "").strip()
    prev = None
    while name and name != prev:
        prev = name
        name = CHANNEL_NOISE_RE.sub("", name).strip(" -\u2013\u2014")
    return name


def strip_title_noise(title: str) -> str:
    prev = None
    out = (title or "").strip()
    while out != prev:
        prev = out
        out = TITLE_NOISE_RE.sub("", out)
    out = TRAILING_NOISE_RE.sub("", out)
    return out.strip(" -\u2013\u2014|\u00b7").strip()


def split_artist_title(info: dict) -> tuple[str, str]:
    raw = (info.get("title") or "").strip()
    cleaned = strip_title_noise(raw)
    channel = clean_channel(info.get("uploader"))


    meta_artist = (info.get("artist") or info.get("creator") or "").strip()
    meta_track = (info.get("track") or "").strip()
    if meta_artist and meta_track:
        return meta_artist.split(",")[0].strip(), meta_track

    for sep in (" - ", " \u2013 ", " \u2014 ", " | "):
        if sep in cleaned:
            left, _, right = cleaned.partition(sep)
            left, right = left.strip(), right.strip()
            if left and right:
                return left, right
    return (channel or "Unknown Artist"), (cleaned or raw or "untitled")


def _coerce_bpm(value) -> int | None:
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        return None
    return n if 40 <= n <= 220 else None


def extract_bpm_key(info: dict) -> tuple[int | None, str | None]:
    haystack = f"{info.get('title') or ''}\n{(info.get('description') or '')[:600]}"
    bpm = None
    m = BPM_RE.search(haystack)
    if m:
        value = int(m.group(1))
        if 40 <= value <= 220:
            bpm = value
    key = None
    m = KEY_RE.search(info.get("title") or "")
    if m:
        if m.group(3):
            key = m.group(3).upper()
        else:
            quality = m.group(2).lower()
            suffix = "minor" if quality in {"minor", "min", "m"} else "major"
            key = f"{m.group(1).replace(chr(9839), '#').replace(chr(9837), 'b')} {suffix}"
    return bpm, key


SAFE_CHARS = re.compile(r"[^a-zA-Z0-9\-_\. ]+")
NAME_CHARS = re.compile(r"[^a-zA-Z0-9\-_\. ()&']+")


def slugify(s: str, fallback: str = "untitled") -> str:
    if not s:
        return fallback
    s = SAFE_CHARS.sub("", s).strip()
    s = re.sub(r"\s+", "-", s).strip("-.").lower()
    return s or fallback


def safe_filename(s: str, fallback: str = "untitled") -> str:
    if not s:
        return fallback
    s = SAFE_CHARS.sub("", s).strip()
    s = re.sub(r"\s+", " ", s)
    return s or fallback


def unique_path(target_dir: Path, base: str, ext: str) -> Path:
    p = target_dir / f"{base}.{ext}"
    counter = 1
    while p.exists():
        p = target_dir / f"{base} ({counter}).{ext}"
        counter += 1
    return p


def write_id3(
    mp3_path: Path,
    info: dict,
    title: str,
    artist: str,
    id3_genre: str,
    bpm: int | None = None,
    musical_key: str | None = None,
) -> None:
    try:
        audio = MP3(mp3_path, ID3=ID3)
        if audio.tags is None:
            audio.add_tags()
        audio.tags["TIT2"] = TIT2(encoding=3, text=title)
        audio.tags["TPE1"] = TPE1(encoding=3, text=artist)
        audio.tags["TCON"] = TCON(encoding=3, text=id3_genre)
        if info.get("uploader"):
            audio.tags["TALB"] = TALB(encoding=3, text=info["uploader"])
        if info.get("upload_date"):
            audio.tags["TDRC"] = TDRC(encoding=3, text=info["upload_date"][:4])


        if bpm:
            audio.tags["TBPM"] = TBPM(encoding=3, text=str(int(bpm)))
        if musical_key:
            audio.tags["TKEY"] = TKEY(encoding=3, text=musical_key)
        audio.save()
    except Exception as e:
        print(f"ID3 tag write failed (non-fatal): {e}", file=sys.stderr)


@app.get("/status")
def status():
    cfg = read_config()
    needs_key = cfg["provider"] in {"anthropic", "openai"}
    return {
        "ok": True,
        "version": VERSION,
        "audio_root": str(audio_root()),
        "video_root": str(video_root()),
        "yt_dlp": shutil.which("yt-dlp") or "python module",
        "yt_dlp_version": yt_dlp_version(),
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "provider": cfg["provider"],
        "model": cfg["model"],
        "has_api_key": (not needs_key) or bool(active_api_key(cfg)),
    }


@app.get("/config")
def get_config():
    raw = _parse_config_file()
    cfg = read_config()
    return {
        "audio_root": str(audio_root()),
        "video_root": str(video_root()),
        "provider": cfg["provider"],
        "model": cfg["model"],
        "has_anthropic_key": bool(cfg["anthropic_api_key"]),
        "has_openai_key": bool(cfg["openai_api_key"]),
        "ollama_url": cfg["ollama_url"],
        "default_ollama_url": DEFAULT_OLLAMA_URL,
        "cookies_from_browser": cfg["cookies_from_browser"],
        "supported_cookie_browsers": sorted(SUPPORTED_COOKIE_BROWSERS),
        "categorize_prompt": raw.get("categorize_prompt") or "",
        "default_prompt": CATEGORIZE_SYSTEM,
        "supported_providers": sorted(SUPPORTED_PROVIDERS),
        "default_models": DEFAULT_MODEL_BY_PROVIDER,
        "active_prompt_is_default": not bool(raw.get("categorize_prompt", "").strip())
        if isinstance(raw.get("categorize_prompt"), str)
        else True,
    }


@app.put("/config")
def put_config(req: ConfigUpdate):
    updates = req.model_dump(exclude_unset=True)

    if "cookies_from_browser" in updates and updates["cookies_from_browser"]:
        value = updates["cookies_from_browser"].lower().strip()
        if value not in SUPPORTED_COOKIE_BROWSERS:
            raise HTTPException(400, f"Unsupported browser: {updates['cookies_from_browser']}")
        updates["cookies_from_browser"] = value

    if "provider" in updates and updates["provider"]:
        if updates["provider"].lower() not in SUPPORTED_PROVIDERS:
            raise HTTPException(400, f"Unsupported provider: {updates['provider']}")
        updates["provider"] = updates["provider"].lower()

    for k in ("audio_root", "video_root"):
        if k in updates and updates[k]:
            try:
                p = Path(updates[k]).expanduser()
                p.mkdir(parents=True, exist_ok=True)
                updates[k] = str(p)
            except (OSError, RuntimeError) as e:
                raise HTTPException(400, f"Cannot use {k}={updates[k]}: {e}") from e

    raw = _parse_config_file()
    if not isinstance(raw, dict):
        raw = {}

    for key, value in updates.items():
        upper = key.upper()
        if value in (None, ""):
            raw.pop(key, None)
            raw.pop(upper, None)
        else:
            raw[key] = value
            raw.pop(upper, None)

    CONFIG_DIR.mkdir(exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(raw, indent=2))
    return {"ok": True}


@app.post("/test-key")
def test_key(req: TestKeyRequest):
    provider = req.provider.lower()
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(400, f"Unsupported provider: {provider}")

    cfg = read_config()

    if provider == "ollama":
        url = (req.url or cfg["ollama_url"] or DEFAULT_OLLAMA_URL).rstrip("/")
        try:
            with urllib.request.urlopen(url + "/api/tags", timeout=4, context=SSL_CONTEXT) as r:
                data = json.loads(r.read().decode("utf-8"))
            models = [m.get("name") for m in data.get("models", []) if m.get("name")]
            return {"ok": True, "models": models[:50]}
        except Exception as e:
            return {"ok": False, "error": str(e)[:300]}

    actual_key = (req.key or "").strip() or (
        cfg["openai_api_key"] if provider == "openai" else cfg["anthropic_api_key"]
    )
    if not actual_key:
        return {"ok": False, "error": "No key provided or configured."}

    try:
        if provider == "anthropic":
            client = Anthropic(api_key=actual_key)
            client.messages.create(
                model=DEFAULT_MODEL_BY_PROVIDER["anthropic"],
                max_tokens=5,
                messages=[{"role": "user", "content": "ok"}],
            )
        else:
            from openai import OpenAI
            client = OpenAI(api_key=actual_key)
            client.chat.completions.create(
                model=DEFAULT_MODEL_BY_PROVIDER["openai"],
                max_completion_tokens=5,
                messages=[{"role": "user", "content": "ok"}],
            )
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


@app.get("/version")
def version_info():
    latest = None
    error = None
    try:
        req = urllib.request.Request(
            REMOTE_VERSION_URL, headers={"User-Agent": "Crateful-Helper"}
        )
        with urllib.request.urlopen(req, timeout=5, context=SSL_CONTEXT) as r:
            latest = r.read().decode().strip()
    except OSError as e:
        error = str(e)
    return {
        "local": VERSION,
        "latest": latest,
        "update_available": bool(latest) and latest != VERSION,
        "error": error,
    }


HELPER_DIR = Path(__file__).resolve().parent
REPO_ROOT = HELPER_DIR.parent
REQUIREMENTS_FILE = HELPER_DIR / "requirements.txt"
REQUIREMENTS_STAMP = HELPER_DIR / ".venv" / ".requirements.sha256"


def yt_dlp_version() -> str | None:
    try:
        return importlib.metadata.version("yt-dlp")
    except importlib.metadata.PackageNotFoundError:
        return None


def _run(cmd: list[str], timeout: int = 300) -> str:
    try:
        res = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=timeout)
    except subprocess.CalledProcessError as e:
        msg = (e.stderr or e.stdout or str(e)).strip()
        raise HTTPException(500, f"{cmd[0]} failed: {msg[-800:]}") from e
    except subprocess.TimeoutExpired as e:
        raise HTTPException(500, f"{cmd[0]} timed out after {timeout}s") from e
    return (res.stdout or "").strip()


def _git(*args: str) -> str:
    return _run(["git", "-C", str(REPO_ROOT), *args])


def _pip(*args: str) -> str:
    return _run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-q", *args])


def _installed_version_subprocess(dist: str) -> str | None:
    code = (
        "import importlib.metadata as m, sys\n"
        "try: print(m.version(sys.argv[1]))\n"
        "except m.PackageNotFoundError: print('')"
    )
    try:
        out = subprocess.run(
            [sys.executable, "-c", code, dist], capture_output=True, text=True, timeout=30
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out or None


def _write_requirements_stamp() -> None:
    try:
        import hashlib

        digest = hashlib.sha256(REQUIREMENTS_FILE.read_bytes()).hexdigest()
        REQUIREMENTS_STAMP.parent.mkdir(parents=True, exist_ok=True)
        REQUIREMENTS_STAMP.write_text(digest + "\n")
    except OSError as e:
        print(f"Could not write requirements stamp (non-fatal): {e}", file=sys.stderr)


def refresh_deps() -> None:
    _pip("-r", str(REQUIREMENTS_FILE))
    _pip("-U", "yt-dlp")
    _write_requirements_stamp()


def restart_argv() -> list[str]:
    return [sys.executable, str(HELPER_DIR / "main.py")]


def schedule_restart(delay: float = 1.0) -> None:

    def _restart():
        time.sleep(delay)
        os.execv(sys.executable, restart_argv())

    threading.Thread(target=_restart, daemon=True).start()


@app.post("/update")
def update():
    if not (REPO_ROOT / ".git").exists():
        raise HTTPException(400, f"Not a git checkout at {REPO_ROOT}. Pull updates manually.")
    before = _git("rev-parse", "HEAD")
    _git("fetch", "--quiet")
    _git("pull", "--ff-only", "--quiet")
    after = _git("rev-parse", "HEAD")

    updated = before != after
    if updated:
        refresh_deps()
        schedule_restart()

    return {
        "ok": True,
        "updated": updated,
        "before": before[:7],
        "after": after[:7],
        "will_restart": updated,
    }


@app.post("/update/yt-dlp")
def update_yt_dlp():
    before = yt_dlp_version()
    _pip("-U", "yt-dlp")
    after = _installed_version_subprocess("yt-dlp") or before
    changed = bool(after) and after != before
    if changed:
        schedule_restart()
    return {
        "ok": True,
        "updated": changed,
        "before": before,
        "after": after,
        "will_restart": changed,
    }


@app.post("/download")
def download(req: DownloadRequest):
    roots = get_roots()
    kind = req.kind if req.kind in roots else "audio"
    base_root = roots[kind]

    if not shutil.which("ffmpeg"):
        raise HTTPException(500, "ffmpeg not found. Run: brew install ffmpeg")

    url = canonical_url(req.url)
    try:
        with yt_dlp.YoutubeDL(ydl_opts(skip_download=True)) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        raise HTTPException(400, f"yt-dlp failed: {friendly_ydl_error(e)}") from e
    if info.get("_type") == "playlist" or info.get("entries"):


        raise HTTPException(
            400, "That link is a playlist. Use the playlist option to download its videos."
        )

    bpm, musical_key = extract_bpm_key(info)
    video_id_hint = extract_video_id(url) or info.get("id")
    ai_error = None

    if req.folder is not None:


        categorized = False
        target_dir = safe_path(kind, req.folder)
        target_dir.mkdir(parents=True, exist_ok=True)
        parts = target_dir.relative_to(base_root).parts
        top = parts[0] if parts else ""
        sub = parts[1] if len(parts) > 1 else ""
        raw_artist, raw_title = split_artist_title(info)
        artist = safe_filename(raw_artist, "Unknown Artist")
        title = safe_filename(raw_title, info.get("title") or "untitled")
        content_type = "music" if kind == "audio" else "other"
        id3_genre = (top or "Unsorted").replace("-", " ").title()
    else:
        decision = None
        try:
            decision = categorize(info, list_folders(base_root), model_override=req.model)
        except HTTPException as e:
            ai_error = str(e.detail)
        except json.JSONDecodeError:
            ai_error = "The AI returned something that was not JSON."
        except Exception as e:
            ai_error = f"{type(e).__name__}: {e}"[:200]

        categorized = decision is not None

        if decision is None:
            top, sub = FALLBACK_TOP, FALLBACK_SUB
            raw_artist, raw_title = split_artist_title(info)
            artist = safe_filename(raw_artist, "Unknown Artist")
            title = safe_filename(raw_title, info.get("title") or "untitled")
            content_type = "music" if kind == "audio" else "other"
            id3_genre = "Unsorted"
            print(f"AI filing unavailable, saving to {top}/{sub}: {ai_error}", file=sys.stderr)
        else:
            content_type = str(decision.get("content_type") or "music").lower()
            if content_type not in CONTENT_TYPES:
                content_type = "music"

            if content_type in FORCED_TOP_BY_TYPE:
                top = FORCED_TOP_BY_TYPE[content_type]
            else:
                top = slugify(decision.get("top_folder"), "unsorted")
            sub = slugify(decision.get("sub_folder"), "general")
            artist = safe_filename(decision.get("artist"), "Unknown Artist")
            title = safe_filename(decision.get("title"), info.get("title") or "untitled")
            id3_genre = (
                decision.get("id3_genre")
                or DEFAULT_ID3_BY_TYPE.get(content_type)
                or sub.replace("-", " ").title()
            )
            bpm = _coerce_bpm(decision.get("bpm")) or bpm
            musical_key = (str(decision.get("musical_key")).strip()
                           if decision.get("musical_key") else None) or musical_key

        target_dir = base_root / top / sub
        target_dir.mkdir(parents=True, exist_ok=True)

    base = NAME_CHARS.sub("", f"{artist} - {title}").strip() or "untitled"


    replaced = None
    if req.force:
        previous = previous_download_path(kind, video_id_hint)
        if previous and previous.exists():
            replaced = str(previous.relative_to(base_root))
            previous.unlink()
            db_delete_file(kind, replaced)

    if kind == "audio":
        final_path = unique_path(target_dir, base, "mp3")
        opts = ydl_opts(
            format="bestaudio/best",
            outtmpl=str(final_path.with_suffix("")) + ".%(ext)s",
            postprocessors=[
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "320",
                }
            ],
        )
        glob_ext = "mp3"
    else:
        final_path = unique_path(target_dir, base, "mp4")
        opts = ydl_opts(
            format="bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            merge_output_format="mp4",
            outtmpl=str(final_path.with_suffix("")) + ".%(ext)s",
        )
        glob_ext = "mp4"

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except Exception as e:
        raise HTTPException(500, f"yt-dlp download failed: {friendly_ydl_error(e)}") from e

    if not final_path.exists():
        candidates = list(target_dir.glob(f"{base}*.{glob_ext}"))
        if candidates:
            final_path = candidates[0]
        else:
            raise HTTPException(500, f"Download completed but {glob_ext.upper()} not found")

    if kind == "audio":
        write_id3(final_path, info, title, artist, id3_genre, bpm, musical_key)

    rel_path = str(final_path.relative_to(base_root))
    video_id = video_id_hint
    record_download(video_id, kind, rel_path)
    try:
        db_upsert_file(
            kind, rel_path,
            source_url=url,
            video_id=video_id,
            title=title,
            artist=artist,
            content_type=content_type,
            duration_sec=float(info["duration"]) if info.get("duration") else None,
        )
    except Exception as e:
        print(f"DB upsert failed (non-fatal): {e}", file=sys.stderr)

    return {
        "success": True,
        "kind": kind,
        "content_type": content_type,
        "path": str(final_path),
        "rel_path": rel_path,
        "top_folder": top,
        "sub_folder": sub,
        "folder": "/".join(x for x in (top, sub) if x),
        "artist": artist,
        "title": title,
        "id3_genre": id3_genre,
        "bpm": bpm,
        "musical_key": musical_key,
        "categorized": categorized,
        "ai_error": ai_error,
        "replaced": replaced,
        "source_url": url,
        "model_used": req.model if categorized else None,
    }


@app.get("/check")
def check(url: str = Query(...)):
    vid = extract_video_id(url)
    result = {"video_id": vid, "audio": None, "video": None}
    if not vid:
        return result
    hist = read_history()
    entry = hist.get(vid, {})
    if not entry:
        return result

    pruned = dict(entry)
    for kind, root in get_roots().items():
        rel = entry.get(kind)
        if rel and (root / rel).exists():
            result[kind] = rel
        elif rel:
            pruned.pop(kind, None)

    if pruned != entry:
        if pruned:
            hist[vid] = pruned
        else:
            hist.pop(vid, None)
        write_history(hist)
    return result


@app.post("/check-bulk")
def check_bulk(req: BulkCheckRequest):
    hist = read_history()
    roots = get_roots()
    out: dict[str, dict] = {}
    for vid in req.video_ids[:500]:
        entry = hist.get(vid) or {}
        found = {}
        for kind, root in roots.items():
            rel = entry.get(kind)
            if rel and (root / rel).exists():
                found[kind] = rel
        if found:
            out[vid] = found
    return {"found": out, "count": len(out)}


@app.get("/library")
def library(root: str = Query("audio")):
    base = root_for(root)
    pattern = "*.mp3" if root == "audio" else "*.mp4"
    items = []
    for f in base.rglob(pattern):
        rel = f.relative_to(base)
        parts = rel.parts
        items.append(
            {
                "rel_path": str(rel),
                "name": f.stem,
                "top_folder": parts[0] if len(parts) > 1 else "",
                "sub_folder": parts[1] if len(parts) > 2 else "",
                "size_bytes": f.stat().st_size,
            }
        )
    items.sort(key=lambda x: (x["top_folder"], x["sub_folder"], x["name"]))
    return {"root": str(base), "kind": root, "count": len(items), "items": items}


@app.get("/browse")
def browse(root: str = Query("audio"), path: str = Query("")):
    target = safe_path(root, path)
    if not target.exists() or not target.is_dir():
        raise HTTPException(404, "Folder not found")


    state_by_path: dict[str, dict] = {}
    try:
        with closing(db_connect()) as conn:
            for r in conn.execute(
                """
                SELECT f.rel_path, f.duration_sec, f.title, f.artist,
                       p.position_sec, p.completed, p.last_played_at
                FROM files f LEFT JOIN playback p ON p.file_id = f.id
                WHERE f.root = ?
                """,
                (root,),
            ).fetchall():
                state_by_path[r["rel_path"]] = {
                    "duration_sec": r["duration_sec"],
                    "title": r["title"],
                    "artist": r["artist"],
                    "position_sec": (r["position_sec"] if r["position_sec"] is not None else 0) or 0,
                    "completed": bool(r["completed"]),
                    "last_played_at": r["last_played_at"],
                }
    except Exception as e:
        print(f"DB join in /browse failed (non-fatal): {e}", file=sys.stderr)

    folders = []
    files = []
    for child in sorted(target.iterdir(), key=lambda p: p.name.lower()):
        if child.name.startswith("."):
            continue
        rel = str(child.relative_to(root_for(root)))
        if child.is_dir():
            try:
                child_count = sum(1 for _ in child.rglob("*") if _.is_file())
            except OSError:
                child_count = 0
            folders.append({"name": child.name, "rel_path": rel, "count": child_count})
        elif child.is_file():
            ext = child.suffix.lower().lstrip(".")
            entry = {
                "name": child.name,
                "stem": child.stem,
                "rel_path": rel,
                "size_bytes": child.stat().st_size,
                "ext": ext,
            }
            state = state_by_path.get(rel)
            if state:
                entry["playback"] = {
                    "position_sec": state["position_sec"],
                    "completed": state["completed"],
                    "duration_sec": state["duration_sec"],
                    "last_played_at": state["last_played_at"],
                }
                if state["title"]:
                    entry["title"] = state["title"]
                if state["artist"]:
                    entry["artist"] = state["artist"]
            files.append(entry)
    base = root_for(root)
    rel_here = "" if target == base else str(target.relative_to(base))
    return {
        "kind": root,
        "root": str(base),
        "path": rel_here,
        "folders": folders,
        "files": files,
    }


@app.get("/file")
def get_file(root: str = Query("audio"), path: str = Query(...)):
    target = safe_path(root, path)
    if not target.exists() or not target.is_file():
        raise HTTPException(404, "File not found")
    media_type = None
    ext = target.suffix.lower()
    if ext == ".mp3":
        media_type = "audio/mpeg"
    elif ext == ".mp4":
        media_type = "video/mp4"
    elif ext == ".m4a":
        media_type = "audio/mp4"
    return FileResponse(target, media_type=media_type, filename=target.name)


@app.post("/reveal")
def reveal(root: str = Query("audio"), path: str = Query("")):
    target = safe_path(root, path)
    if not target.exists():
        raise HTTPException(404, "Path not found")
    system = platform.system()
    if system == "Darwin":
        cmd = ["open", "-R", str(target)]
    elif system == "Linux":
        cmd = ["xdg-open", str(target if target.is_dir() else target.parent)]
    else:
        raise HTTPException(501, f"Reveal is not supported on {system}")
    try:
        subprocess.run(cmd, check=False)
        return {"ok": True, "revealed": str(target)}
    except OSError as e:
        raise HTTPException(500, f"{cmd[0]} failed: {e}") from e


@app.delete("/file")
def delete_file(root: str = Query("audio"), path: str = Query(...)):
    target = safe_path(root, path)
    if not target.exists() or not target.is_file():
        raise HTTPException(404, "File not found")
    target.unlink()
    hist = read_history()
    changed = False
    for vid, entry in list(hist.items()):
        if entry.get(root) == path:
            entry.pop(root, None)
            changed = True
            if not entry:
                hist.pop(vid)
    if changed:
        write_history(hist)
    try:
        db_delete_file(root, path)
    except Exception as e:
        print(f"DB delete failed (non-fatal): {e}", file=sys.stderr)
    return {"ok": True, "deleted": str(target)}


@app.get("/db/file")
def db_file_endpoint(root: str = Query(...), path: str = Query(...)):
    if root not in get_roots():
        raise HTTPException(400, f"Invalid root: {root}")
    target = safe_path(root, path)
    record = db_get_file(root, path)
    if record is None:
        if not target.exists():
            raise HTTPException(404, "File not found")
        db_upsert_file(root, path)
        record = db_get_file(root, path)
    return record


@app.post("/db/position")
def db_position_endpoint(req: PositionUpdate):
    if req.root not in get_roots():
        raise HTTPException(400, f"Invalid root: {req.root}")
    db_update_position(req.root, req.path, req.position_sec, req.duration_sec)
    return {"ok": True}


@app.post("/db/completed")
def db_completed_endpoint(req: CompletedUpdate):
    if req.root not in get_roots():
        raise HTTPException(400, f"Invalid root: {req.root}")
    db_mark_completed(req.root, req.path, req.completed)
    return {"ok": True}


@app.get("/db/continue")
def db_continue_endpoint(root: str = Query("audio"), limit: int = Query(20, ge=1, le=200)):
    if root not in get_roots():
        raise HTTPException(400, f"Invalid root: {root}")
    return {"items": db_continue_listening(root, limit)}


@app.post("/db/backfill")
def db_backfill_endpoint():
    added = db_backfill_from_disk()
    return {"ok": True, "added": added}


@app.post("/file/rename")
def rename_file(req: RenameRequest):
    if "/" in req.new_name or "\\" in req.new_name or req.new_name.startswith("."):
        raise HTTPException(400, "Name may not contain path separators or start with a dot")
    old = safe_path(req.root, req.old_path)
    if not old.is_file():
        raise HTTPException(404, "File not found")

    clean = NAME_CHARS.sub("", req.new_name).strip()
    if not clean:
        raise HTTPException(400, "Name is empty after sanitization")
    if "." not in clean:
        clean = clean + old.suffix
    new_target = old.parent / clean
    if new_target.exists() and new_target != old:
        raise HTTPException(409, f"A file named '{clean}' already exists here")

    old.rename(new_target)
    new_rel = str(new_target.relative_to(root_for(req.root)))
    try:
        db_update_path(req.root, req.old_path, new_rel)
        history_update_path(req.root, req.old_path, new_rel)
    except Exception as e:
        print(f"DB/history update after rename failed (non-fatal): {e}", file=sys.stderr)
    return {"ok": True, "new_path": new_rel}


@app.post("/file/move")
def move_file_endpoint(req: MoveRequest):
    old = safe_path(req.root, req.old_path)
    if not old.is_file():
        raise HTTPException(404, "File not found")

    base = root_for(req.root)
    raw_dir = (req.new_dir or "").strip("/")
    if raw_dir:
        new_dir = safe_path(req.root, raw_dir)
        new_dir.mkdir(parents=True, exist_ok=True)
    else:
        new_dir = base

    new_target = new_dir / old.name
    if new_target.exists() and new_target != old:
        raise HTTPException(409, f"A file named '{old.name}' already exists at {raw_dir or '/'}")

    if new_target == old:
        return {"ok": True, "new_path": req.old_path, "moved": False}

    shutil.move(str(old), str(new_target))
    new_rel = str(new_target.relative_to(base))
    try:
        db_update_path(req.root, req.old_path, new_rel)
        history_update_path(req.root, req.old_path, new_rel)
    except Exception as e:
        print(f"DB/history update after move failed (non-fatal): {e}", file=sys.stderr)
    return {"ok": True, "new_path": new_rel, "moved": True}


@app.post("/folder/create")
def create_folder(req: CreateFolderRequest):
    target = safe_path(req.root, req.path)
    if target.exists() and target.is_dir():
        return {"ok": True, "existed": True, "path": req.path}
    target.mkdir(parents=True, exist_ok=True)
    return {"ok": True, "existed": False, "path": req.path}


@app.post("/file/reclassify")
def reclassify(req: ReclassifyRequest):
    old = safe_path(req.root, req.path)
    if not old.is_file():
        raise HTTPException(404, "File not found")

    record = db_get_file(req.root, req.path)
    if not record or not record.get("source_url"):
        raise HTTPException(400, "No source URL recorded for this file — cannot reclassify")

    source_url = record["source_url"]
    try:
        with yt_dlp.YoutubeDL(ydl_opts(skip_download=True)) as ydl:
            info = ydl.extract_info(canonical_url(source_url), download=False)
    except Exception as e:
        raise HTTPException(400, f"yt-dlp failed: {friendly_ydl_error(e)}") from e

    base_root = root_for(req.root)
    try:
        decision = categorize(info, list_folders(base_root))
    except json.JSONDecodeError as e:
        raise HTTPException(500, f"AI returned invalid JSON: {e}") from e

    content_type = str(decision.get("content_type") or "music").lower()
    if content_type not in CONTENT_TYPES:
        content_type = "music"
    if content_type in FORCED_TOP_BY_TYPE:
        top = FORCED_TOP_BY_TYPE[content_type]
    else:
        top = slugify(decision.get("top_folder"), "unsorted")
    sub = slugify(decision.get("sub_folder"), "general")

    new_dir = base_root / top / sub
    new_dir.mkdir(parents=True, exist_ok=True)
    new_target = new_dir / old.name

    if new_target == old:
        try:
            db_update_content_type(req.root, req.path, content_type)
        except Exception as e:
            print(f"DB content_type update failed (non-fatal): {e}", file=sys.stderr)
        return {
            "ok": True,
            "moved": False,
            "folder": f"{top}/{sub}",
            "content_type": content_type,
            "new_path": req.path,
        }

    counter = 1
    while new_target.exists():
        new_target = new_dir / f"{old.stem} ({counter}){old.suffix}"
        counter += 1

    shutil.move(str(old), str(new_target))
    new_rel = str(new_target.relative_to(base_root))
    try:
        db_update_path(req.root, req.path, new_rel)
        db_update_content_type(req.root, new_rel, content_type)
        history_update_path(req.root, req.path, new_rel)
    except Exception as e:
        print(f"DB/history update after reclassify failed (non-fatal): {e}", file=sys.stderr)

    return {
        "ok": True,
        "moved": True,
        "new_path": new_rel,
        "folder": f"{top}/{sub}",
        "content_type": content_type,
    }


@app.get("/folders")
def list_all_folders(root: str = Query(...)):
    base = root_for(root)
    out = []
    for child in base.rglob("*"):
        if child.is_dir() and not child.name.startswith("."):
            out.append(str(child.relative_to(base)))
    out.sort()
    return {"root": root, "folders": out, "recent": recent_folders(root)}


def recent_folders(root: str, limit: int = 8) -> list[str]:
    base = root_for(root)
    seen: list[str] = []
    try:
        with closing(db_connect()) as conn:
            rows = conn.execute(
                "SELECT rel_path FROM files WHERE root = ? ORDER BY added_at DESC LIMIT 400",
                (root,),
            ).fetchall()
    except sqlite3.Error as e:
        print(f"recent_folders query failed (non-fatal): {e}", file=sys.stderr)
        return []
    for r in rows:
        folder = str(Path(r["rel_path"]).parent)
        if folder in (".", ""):
            continue
        if folder in seen:
            continue
        if not (base / folder).is_dir():
            continue
        seen.append(folder)
        if len(seen) >= limit:
            break
    return seen


PATH_PRESETS = {
    "home": Path.home(),
    "desktop": Path.home() / "Desktop",
    "downloads": Path.home() / "Downloads",
    "music": Path.home() / "Music",
    "documents": Path.home() / "Documents",
}


@app.get("/path-presets")
def path_presets():
    out = []
    for name, path in PATH_PRESETS.items():
        out.append({
            "name": name,
            "label": name.title(),
            "audio": str(path / "Crateful"),
            "video": str(path / "Crateful Video"),
            "exists": path.is_dir(),
        })
    return {"presets": [p for p in out if p["exists"]], "home": str(Path.home())}


try:
    db_init()
    _added = db_backfill_from_disk()
    if _added:
        print(f"DB backfilled {_added} file(s) from disk", file=sys.stderr)
except Exception as _e:
    print(f"DB init/backfill failed (non-fatal): {_e}", file=sys.stderr)


if __name__ == "__main__":
    import uvicorn

    print(f"Crateful helper {VERSION} starting on http://127.0.0.1:{PORT}")
    print(f"Audio library: {audio_root()}")
    print(f"Video library: {video_root()}")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")
