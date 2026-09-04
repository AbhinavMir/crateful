"""Canonical URLs, playlist handling, and forced re-download."""

import pytest
from conftest import URL, FakeYDL, touch


@pytest.mark.parametrize(
    "given,expected",
    [
        # The dangerous one: yt-dlp reads &list= as a playlist and pulls every entry.
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL123&index=2",
         "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s",
         "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&pp=ygUJcmljaw%3D%3D",
         "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ?t=30&si=abc",
         "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ",
         "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        ("https://m.youtube.com/watch?app=desktop&v=dQw4w9WgXcQ",
         "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        # Unparseable input is passed through rather than mangled.
        ("https://example.com/video", "https://example.com/video"),
        ("", ""),
    ],
)
def test_canonical_url(main_module, given, expected):
    assert main_module.canonical_url(given) == expected


def test_download_strips_playlist_param(client, roots, fake_ydl, monkeypatch):
    seen = {}
    orig_info = FakeYDL.extract_info
    orig_download = FakeYDL.download

    def spy(self, url, download=False):
        seen["info_url"] = url
        return orig_info(self, url, download)

    def spy_dl(self, urls):
        seen["dl_urls"] = list(urls)
        orig_download(self, urls)

    monkeypatch.setattr(FakeYDL, "extract_info", spy)
    monkeypatch.setattr(FakeYDL, "download", spy_dl)

    messy = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLbig&index=7&t=90s"
    r = client.post("/download", json={"url": messy, "kind": "audio", "folder": "house"})
    assert r.status_code == 200, r.text
    assert seen["info_url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert seen["dl_urls"] == ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]
    assert r.json()["source_url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_download_sets_noplaylist(client, roots, fake_ydl, monkeypatch):
    opts = {}
    orig_init = FakeYDL.__init__

    def spy_init(self, o):
        opts.update(o)
        orig_init(self, o)

    monkeypatch.setattr(FakeYDL, "__init__", spy_init)
    client.post("/download", json={"url": URL, "kind": "audio", "folder": "x"})
    assert opts.get("noplaylist") is True


def test_download_refuses_a_playlist_result(client, roots, fake_ydl, monkeypatch):
    monkeypatch.setattr(FakeYDL, "extract_info",
                        lambda self, url, download=False: {"_type": "playlist", "entries": [{}, {}]})
    r = client.post("/download", json={"url": "https://example.com/x", "kind": "audio"})
    assert r.status_code == 400
    assert "playlist" in r.json()["detail"].lower()


# --- playlist listing -------------------------------------------------------

def test_playlist_lists_entries(client, main_module, monkeypatch):
    class PL:
        def __init__(self, opts): self.opts = opts
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def extract_info(self, url, download=False):
            assert self.opts["noplaylist"] is False
            assert self.opts["extract_flat"] == "in_playlist"
            return {"title": "My Mix", "entries": [
                {"id": "aaaaaaaaaaa", "title": "One", "duration": 100},
                {"id": "bbbbbbbbbbb", "title": "Two", "duration": 200},
                None,
                {"title": "no id"},
            ]}

    monkeypatch.setattr(main_module.yt_dlp, "YoutubeDL", PL)
    body = client.get("/playlist", params={"url": "https://youtube.com/playlist?list=PL1"}).json()
    assert body["is_playlist"] is True
    assert body["title"] == "My Mix"
    assert body["count"] == 2
    assert [e["video_id"] for e in body["entries"]] == ["aaaaaaaaaaa", "bbbbbbbbbbb"]
    assert body["entries"][0]["url"] == "https://www.youtube.com/watch?v=aaaaaaaaaaa"


def test_playlist_on_a_single_video(client, main_module, monkeypatch):
    class Single:
        def __init__(self, opts): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def extract_info(self, url, download=False):
            return {"id": "x", "title": "Just one"}

    monkeypatch.setattr(main_module.yt_dlp, "YoutubeDL", Single)
    body = client.get("/playlist", params={"url": URL}).json()
    assert body["is_playlist"] is False
    assert body["entries"] == []


def test_playlist_respects_the_limit(client, main_module, monkeypatch):
    class Big:
        def __init__(self, opts): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def extract_info(self, url, download=False):
            return {"title": "Big", "entries": [
                {"id": f"{i:011d}", "title": str(i)} for i in range(50)
            ]}

    monkeypatch.setattr(main_module.yt_dlp, "YoutubeDL", Big)
    body = client.get("/playlist", params={"url": "u", "limit": 10}).json()
    assert body["count"] == 10
    assert body["truncated"] is True


# --- force re-download ------------------------------------------------------

def test_force_replaces_the_previous_file(client, roots, main_module, fake_ydl):
    first = client.post("/download", json={"url": URL, "kind": "audio", "folder": "house"})
    old_rel = first.json()["rel_path"]
    assert (roots["audio"] / old_rel).exists()

    again = client.post("/download",
                        json={"url": URL, "kind": "audio", "folder": "house", "force": True})
    assert again.status_code == 200, again.text
    body = again.json()
    assert body["replaced"] == old_rel
    assert body["rel_path"] == old_rel                     # same name, not "(1)"
    assert len(list((roots["audio"] / "house").glob("*.mp3"))) == 1


def test_without_force_a_second_copy_appears(client, roots, fake_ydl):
    client.post("/download", json={"url": URL, "kind": "audio", "folder": "house"})
    second = client.post("/download", json={"url": URL, "kind": "audio", "folder": "house"})
    assert second.json()["replaced"] is None
    assert second.json()["rel_path"].endswith("(1).mp3")
    assert len(list((roots["audio"] / "house").glob("*.mp3"))) == 2


def test_force_can_move_the_file_to_another_folder(client, roots, fake_ydl):
    client.post("/download", json={"url": URL, "kind": "audio", "folder": "house"})
    r = client.post("/download",
                    json={"url": URL, "kind": "audio", "folder": "techno", "force": True})
    assert r.json()["rel_path"].startswith("techno/")
    assert list((roots["audio"] / "house").glob("*.mp3")) == []


def test_force_with_nothing_to_replace_is_fine(client, roots, fake_ydl):
    r = client.post("/download",
                    json={"url": URL, "kind": "audio", "folder": "house", "force": True})
    assert r.status_code == 200
    assert r.json()["replaced"] is None


def test_force_only_touches_the_matching_kind(client, roots, fake_ydl):
    client.post("/download", json={"url": URL, "kind": "audio", "folder": "a"})
    client.post("/download", json={"url": URL, "kind": "video", "folder": "a"})
    r = client.post("/download", json={"url": URL, "kind": "audio", "folder": "a", "force": True})
    assert r.json()["replaced"] is not None
    assert list((roots["video"] / "a").glob("*.mp4"))          # video untouched


def test_previous_download_path_needs_a_real_file(client, roots, main_module):
    main_module.record_download("dQw4w9WgXcQ", "audio", "gone/x.mp3")
    assert main_module.previous_download_path("audio", "dQw4w9WgXcQ") is None
    touch(roots["audio"] / "gone/x.mp3")
    assert main_module.previous_download_path("audio", "dQw4w9WgXcQ").name == "x.mp3"
    assert main_module.previous_download_path("audio", None) is None
