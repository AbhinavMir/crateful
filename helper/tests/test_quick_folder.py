"""Downloading into a folder the user picked, with no AI call."""

import pytest
from conftest import URL, FakeYDL, touch


def test_explicit_folder_skips_the_model(client, roots, fake_ydl, main_module, monkeypatch):
    called = []
    monkeypatch.setattr(main_module, "categorize",
                        lambda *a, **k: called.append(True) or {})
    r = client.post("/download", json={"url": URL, "kind": "audio", "folder": "house/deep-house"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert called == []                      # the whole point: no API call, no cost
    assert body["categorized"] is False
    assert body["model_used"] is None
    assert body["folder"] == "house/deep-house"
    assert body["rel_path"] == "house/deep-house/Artist - Song.mp3"
    assert (roots["audio"] / body["rel_path"]).exists()


def test_explicit_folder_derives_artist_and_title(client, roots, fake_ydl):
    r = client.post("/download", json={"url": URL, "kind": "audio", "folder": "house"})
    body = r.json()
    # FakeYDL's title is "Artist - Song (Official Video)".
    assert body["artist"] == "Artist"
    assert body["title"] == "Song"
    assert body["top_folder"] == "house"
    assert body["sub_folder"] == ""


def test_explicit_folder_creates_a_new_one(client, roots, fake_ydl):
    r = client.post("/download", json={"url": URL, "kind": "audio", "folder": "new-genre/new-sub"})
    assert r.status_code == 200
    assert (roots["audio"] / "new-genre/new-sub").is_dir()


def test_explicit_root_folder(client, roots, fake_ydl):
    r = client.post("/download", json={"url": URL, "kind": "audio", "folder": ""})
    assert r.status_code == 200, r.text
    assert r.json()["rel_path"] == "Artist - Song.mp3"
    assert r.json()["folder"] == ""


def test_explicit_folder_blocks_traversal(client, roots, fake_ydl):
    r = client.post("/download", json={"url": URL, "kind": "audio", "folder": "../escape"})
    assert r.status_code == 400
    assert not (roots["audio"].parent / "escape").exists()


def test_explicit_folder_for_video_uses_video_root(client, roots, fake_ydl):
    r = client.post("/download", json={"url": URL, "kind": "video", "folder": "sets"})
    assert r.status_code == 200, r.text
    assert (roots["video"] / "sets/Artist - Song.mp4").exists()
    assert not (roots["audio"] / "sets").exists()


def test_omitting_folder_still_uses_the_model(client, roots, fake_ydl, decision):
    r = client.post("/download", json={"url": URL, "kind": "audio"})
    assert r.json()["categorized"] is True
    assert r.json()["folder"] == "pop/synth-pop"


# --- recent folders ---------------------------------------------------------

def test_recent_folders_newest_first(client, roots, main_module):
    for rel in ["a/one.mp3", "b/two.mp3", "c/three.mp3"]:
        touch(roots["audio"] / rel)
        main_module.db_upsert_file("audio", rel)
    # Force a known ordering.
    from contextlib import closing
    with closing(main_module.db_connect()) as conn:
        for ts, rel in [(100, "a/one.mp3"), (300, "b/two.mp3"), (200, "c/three.mp3")]:
            conn.execute("UPDATE files SET added_at=? WHERE rel_path=?", (ts, rel))
        conn.commit()
    assert main_module.recent_folders("audio") == ["b", "c", "a"]


def test_recent_folders_skips_deleted_and_root_level(client, roots, main_module):
    touch(roots["audio"] / "gone/x.mp3")
    touch(roots["audio"] / "loose.mp3")
    main_module.db_upsert_file("audio", "gone/x.mp3")
    main_module.db_upsert_file("audio", "loose.mp3")
    (roots["audio"] / "gone/x.mp3").unlink()
    (roots["audio"] / "gone").rmdir()
    assert main_module.recent_folders("audio") == []


def test_recent_folders_deduplicates(client, roots, main_module):
    for rel in ["house/a.mp3", "house/b.mp3", "techno/c.mp3"]:
        touch(roots["audio"] / rel)
        main_module.db_upsert_file("audio", rel)
    assert sorted(main_module.recent_folders("audio")) == ["house", "techno"]


def test_folders_endpoint_includes_recent(client, roots, main_module):
    touch(roots["audio"] / "house/deep/a.mp3")
    main_module.db_upsert_file("audio", "house/deep/a.mp3")
    body = client.get("/folders", params={"root": "audio"}).json()
    assert body["folders"] == ["house", "house/deep"]
    assert body["recent"] == ["house/deep"]


# --- path presets -----------------------------------------------------------

def test_path_presets_only_lists_real_directories(client):
    body = client.get("/path-presets").json()
    names = [p["name"] for p in body["presets"]]
    assert "home" in names
    for p in body["presets"]:
        assert p["exists"] is True
        assert p["audio"].endswith("Crateful")
        assert p["video"].endswith("Crateful Video")


# --- metadata heuristics ----------------------------------------------------

@pytest.mark.parametrize(
    "info,expected",
    [
        ({"title": "ODESZA - Line Of Sight (Lane 8 Remix) [Official Audio]", "uploader": "ODESZAVEVO"},
         ("ODESZA", "Line Of Sight (Lane 8 Remix)")),
        ({"title": "Peggy Gou | Boiler Room Berlin", "uploader": "Boiler Room"},
         ("Peggy Gou", "Boiler Room Berlin")),
        ({"title": "Track (Official Music Video)", "uploader": "Cool Records"},
         ("Cool", "Track")),
        ({"title": "No Separator Here", "uploader": "Someone - Topic"},
         ("Someone", "No Separator Here")),
        ({"title": "x", "uploader": "c", "artist": "Real Artist, Guest", "track": "Real Track"},
         ("Real Artist", "Real Track")),
        ({"title": "", "uploader": ""}, ("Unknown Artist", "untitled")),
    ],
)
def test_split_artist_title(main_module, info, expected):
    assert main_module.split_artist_title(info) == expected


@pytest.mark.parametrize(
    "info,bpm,key",
    [
        ({"title": "Deep Cut 128 BPM F# minor"}, 128, "F# minor"),
        ({"title": "Banger [8A] 174bpm"}, 174, "8A"),
        ({"title": "Track", "description": "Tempo: 120 bpm"}, 120, None),
        ({"title": "Track in Gm"}, None, "G minor"),
        ({"title": "No numbers here"}, None, None),
        ({"title": "Year 2024 track"}, None, None),          # 2024 is not a BPM
        ({"title": "Released 1999 bpm-free"}, None, None),   # out of range
    ],
)
def test_extract_bpm_key(main_module, info, bpm, key):
    assert main_module.extract_bpm_key(info) == (bpm, key)


def test_bpm_and_key_land_in_the_response(client, roots, fake_ydl, main_module, monkeypatch):
    monkeypatch.setattr(FakeYDL, "extract_info",
                        lambda self, url, download=False: {
                            "id": "x", "title": "A - B 126 BPM Am", "uploader": "U", "duration": 10})
    r = client.post("/download", json={"url": URL, "kind": "audio", "folder": "house"})
    assert r.json()["bpm"] == 126
    assert r.json()["musical_key"] == "A minor"


def test_model_bpm_is_range_checked(main_module):
    assert main_module._coerce_bpm("128") == 128
    assert main_module._coerce_bpm(128.0) == 128
    assert main_module._coerce_bpm(None) is None
    assert main_module._coerce_bpm("fast") is None
    assert main_module._coerce_bpm(9999) is None
    assert main_module._coerce_bpm(10) is None
