import json
import os
import sys
from contextlib import closing
from pathlib import Path

import pytest

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
