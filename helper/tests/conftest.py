import json
import os
import sys
from contextlib import closing
from pathlib import Path

import pytest

URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
INFO = {
    "id": "dQw4w9WgXcQ",
    "title": "Artist - Song (Official Video)",
    "uploader": "ArtistVEVO",
    "duration": 213,
    "tags": ["pop"],
    "categories": ["Music"],
    "description": "desc",
    "upload_date": "20240101",
}

HELPER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HELPER_DIR))


@pytest.fixture(scope="session")
def home(tmp_path_factory):
    """Isolated ~/.ytd_dj replacement. Must be set before `main` is imported."""
    h = tmp_path_factory.mktemp("ytd_home")
    os.environ["YTD_DJ_HOME"] = str(h)
    roots = h / "roots"
    (roots / "audio").mkdir(parents=True)
    (roots / "video").mkdir(parents=True)
    (h / "config.json").write_text(
        json.dumps({"audio_root": str(roots / "audio"), "video_root": str(roots / "video")})
    )
    return h


@pytest.fixture(scope="session")
def main_module(home):
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OLLAMA_URL", "YTD_PROVIDER", "YTD_MODEL"):
        os.environ.pop(var, None)
    import main

    # Hard guard: never let the suite touch the real user library.
    assert main.CONFIG_DIR == home, f"CONFIG_DIR={main.CONFIG_DIR}, expected {home}"
    assert str(home) in str(main.audio_root())
    return main


@pytest.fixture
def roots(home, main_module, tmp_path):
    """Fresh audio/video roots and an empty DB for each test."""
    audio = tmp_path / "audio"
    video = tmp_path / "video"
    audio.mkdir()
    video.mkdir()
    (home / "config.json").write_text(
        json.dumps({"audio_root": str(audio), "video_root": str(video)})
    )
    with closing(main_module.db_connect()) as conn:
        conn.execute("DELETE FROM playback")
        conn.execute("DELETE FROM tags")
        conn.execute("DELETE FROM files")
        conn.commit()
    main_module.write_history({})
    return {"audio": audio, "video": video}


@pytest.fixture
def client(main_module, roots):
    from fastapi.testclient import TestClient

    return TestClient(main_module.app)


def touch(path: Path, size: int = 16) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * size)
    return path


class FakeYDL:
    """Stands in for yt_dlp.YoutubeDL: fixed metadata, writes a stub file."""

    fail_download = False

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download=False):
        return dict(INFO)

    def download(self, urls):
        if FakeYDL.fail_download:
            raise RuntimeError("HTTP Error 403")
        is_audio = any(
            pp.get("preferredcodec") == "mp3" for pp in self.opts.get("postprocessors", [])
        )
        out = self.opts["outtmpl"].replace("%(ext)s", "mp3" if is_audio else "mp4")
        Path(out).write_bytes(b"\x00" * 32)


@pytest.fixture
def fake_ydl(main_module, monkeypatch):
    FakeYDL.fail_download = False
    monkeypatch.setattr(main_module.yt_dlp, "YoutubeDL", FakeYDL)
    monkeypatch.setattr(main_module.shutil, "which", lambda name: f"/usr/bin/{name}")
    return FakeYDL


@pytest.fixture
def decision(main_module, monkeypatch):
    """Fakes the AI call and records how it was invoked."""
    state = {
        "value": {
            "content_type": "music",
            "top_folder": "Pop!",
            "sub_folder": "Synth Pop",
            "artist": "Artist",
            "title": "Song",
            "id3_genre": "Synth Pop",
        },
        "calls": [],
    }

    def fake(info, folders, model_override=None):
        state["calls"].append({"info": info, "folders": folders, "model": model_override})
        return state["value"]

    monkeypatch.setattr(main_module, "categorize", fake)
    return state
