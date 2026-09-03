import json
from pathlib import Path

import pytest
from conftest import touch

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


class FakeYDL:
    """Stands in for yt_dlp.YoutubeDL: returns fixed metadata and writes a stub file."""

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
        is_audio = any(pp.get("preferredcodec") == "mp3" for pp in self.opts.get("postprocessors", []))
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


def test_audio_download_places_file_and_records(client, roots, main_module, fake_ydl, decision):
    r = client.post("/download", json={"url": URL, "kind": "audio", "model": "claude-x"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["folder"] == "pop/synth-pop"
    assert body["rel_path"] == "pop/synth-pop/Artist - Song.mp3"
    assert body["model_used"] == "claude-x"
    assert (roots["audio"] / body["rel_path"]).exists()
    assert decision["calls"][0]["model"] == "claude-x"

    rec = main_module.db_get_file("audio", body["rel_path"])
    assert rec["source_url"] == URL
    assert rec["video_id"] == "dQw4w9WgXcQ"
    assert rec["content_type"] == "music"
    assert rec["duration_sec"] == 213
    assert client.get("/check", params={"url": URL}).json()["audio"] == body["rel_path"]


def test_second_download_gets_unique_name(client, roots, fake_ydl, decision):
    touch(roots["audio"] / "pop/synth-pop/Artist - Song.mp3")
    r = client.post("/download", json={"url": URL, "kind": "audio"})
    assert r.json()["rel_path"] == "pop/synth-pop/Artist - Song (1).mp3"


def test_video_download_uses_video_root(client, roots, fake_ydl, decision):
    r = client.post("/download", json={"url": URL, "kind": "video"})
    assert r.status_code == 200, r.text
    assert r.json()["rel_path"] == "pop/synth-pop/Artist - Song.mp4"
    assert (roots["video"] / "pop/synth-pop/Artist - Song.mp4").exists()
    assert not (roots["audio"] / "pop").exists()


@pytest.mark.parametrize(
    "content_type,top",
    [("podcast", "podcasts"), ("spoken", "spoken"), ("other", "other"), ("garbage", "pop")],
)
def test_forced_top_folder_by_content_type(client, roots, fake_ydl, decision, content_type, top):
    decision["value"] = dict(decision["value"], content_type=content_type)
    r = client.post("/download", json={"url": URL, "kind": "audio"})
    assert r.json()["top_folder"] == top


def test_existing_folders_are_sent_to_categorizer(client, roots, fake_ydl, decision):
    (roots["audio"] / "house/deep").mkdir(parents=True)
    client.post("/download", json={"url": URL, "kind": "audio"})
    assert decision["calls"][0]["folders"] == [{"name": "house", "subs": ["deep"]}]


def test_download_failure_is_500_and_leaves_no_file(client, roots, fake_ydl, decision):
    fake_ydl.fail_download = True
    r = client.post("/download", json={"url": URL, "kind": "audio"})
    assert r.status_code == 500
    assert "download failed" in r.json()["detail"]
    assert list(roots["audio"].rglob("*.mp3")) == []


def test_invalid_ai_json_is_500(client, roots, fake_ydl, main_module, monkeypatch):
    def bad(info, folders, model_override=None):
        raise json.JSONDecodeError("x", "y", 0)

    monkeypatch.setattr(main_module, "categorize", bad)
    r = client.post("/download", json={"url": URL, "kind": "audio"})
    assert r.status_code == 500
    assert "invalid JSON" in r.json()["detail"]


def test_missing_ffmpeg_is_500(client, roots, main_module, monkeypatch, decision):
    monkeypatch.setattr(main_module.shutil, "which", lambda name: None)
    r = client.post("/download", json={"url": URL, "kind": "audio"})
    assert r.status_code == 500
    assert "ffmpeg" in r.json()["detail"]


def test_reclassify_moves_file(client, roots, main_module, fake_ydl, decision):
    touch(roots["audio"] / "unsorted/general/Artist - Song.mp3")
    main_module.db_upsert_file("audio", "unsorted/general/Artist - Song.mp3", source_url=URL)
    r = client.post("/file/reclassify", json={"root": "audio", "path": "unsorted/general/Artist - Song.mp3"})
    assert r.status_code == 200, r.text
    assert r.json()["moved"] is True
    assert r.json()["new_path"] == "pop/synth-pop/Artist - Song.mp3"
    assert (roots["audio"] / "pop/synth-pop/Artist - Song.mp3").exists()
    assert main_module.db_get_file("audio", "pop/synth-pop/Artist - Song.mp3")["content_type"] == "music"


def test_reclassify_without_source_url(client, roots, main_module, fake_ydl, decision):
    touch(roots["audio"] / "a.mp3")
    r = client.post("/file/reclassify", json={"root": "audio", "path": "a.mp3"})
    assert r.status_code == 400
