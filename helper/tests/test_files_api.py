from conftest import touch


def test_browse_root_lists_folders_and_files(client, roots):
    touch(roots["audio"] / "house/deep/a.mp3")
    touch(roots["audio"] / "house/deep/b.mp3")
    touch(roots["audio"] / "loose.mp3")
    touch(roots["audio"] / ".hidden.mp3")

    r = client.get("/browse", params={"root": "audio", "path": ""})
    assert r.status_code == 200
    body = r.json()
    assert body["path"] == ""
    assert [f["name"] for f in body["folders"]] == ["house"]
    assert body["folders"][0]["count"] == 2
    assert [f["name"] for f in body["files"]] == ["loose.mp3"]

    r = client.get("/browse", params={"root": "audio", "path": "house/deep"})
    assert r.json()["path"] == "house/deep"
    assert sorted(f["rel_path"] for f in r.json()["files"]) == ["house/deep/a.mp3", "house/deep/b.mp3"]


def test_browse_missing_and_traversal(client, roots):
    assert client.get("/browse", params={"root": "audio", "path": "nope"}).status_code == 404
    assert client.get("/browse", params={"root": "audio", "path": "../"}).status_code == 400


def test_library_flat_list(client, roots):
    touch(roots["audio"] / "house/deep/a.mp3")
    touch(roots["audio"] / "b.mp3")
    touch(roots["video"] / "v.mp4")
    r = client.get("/library", params={"root": "audio"})
    assert r.json()["count"] == 2
    items = {i["rel_path"]: i for i in r.json()["items"]}
    assert items["house/deep/a.mp3"]["top_folder"] == "house"
    assert items["house/deep/a.mp3"]["sub_folder"] == "deep"
    assert items["b.mp3"]["top_folder"] == ""
    assert client.get("/library", params={"root": "video"}).json()["count"] == 1


def test_get_file_streams_with_media_type(client, roots):
    touch(roots["audio"] / "a.mp3", size=100)
    r = client.get("/file", params={"root": "audio", "path": "a.mp3"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("audio/mpeg")
    assert len(r.content) == 100
    assert client.get("/file", params={"root": "audio", "path": "missing.mp3"}).status_code == 404
    assert client.get("/file", params={"root": "audio", "path": "../x"}).status_code == 400


def test_delete_file_cleans_history_and_db(client, roots, main_module):
    touch(roots["audio"] / "a.mp3")
    main_module.record_download("vid00000001", "audio", "a.mp3")
    main_module.db_upsert_file("audio", "a.mp3", title="A")

    r = client.delete("/file", params={"root": "audio", "path": "a.mp3"})
    assert r.status_code == 200
    assert not (roots["audio"] / "a.mp3").exists()
    assert main_module.read_history() == {}
    assert main_module.db_get_file("audio", "a.mp3") is None
    assert client.delete("/file", params={"root": "audio", "path": "a.mp3"}).status_code == 404


def test_folders_and_create(client, roots):
    r = client.post("/folder/create", json={"root": "audio", "path": "techno/melodic"})
    assert r.json() == {"ok": True, "existed": False, "path": "techno/melodic"}
    assert (roots["audio"] / "techno/melodic").is_dir()
    assert client.post("/folder/create", json={"root": "audio", "path": "techno/melodic"}).json()["existed"] is True
    assert client.post("/folder/create", json={"root": "audio", "path": "../esc"}).status_code == 400
    assert client.get("/folders", params={"root": "audio"}).json()["folders"] == ["techno", "techno/melodic"]


def test_rename(client, roots, main_module):
    touch(roots["audio"] / "house/a.mp3")
    main_module.db_upsert_file("audio", "house/a.mp3", title="A")
    main_module.record_download("vid00000002", "audio", "house/a.mp3")

    r = client.post("/file/rename", json={"root": "audio", "old_path": "house/a.mp3", "new_name": "b"})
    assert r.status_code == 200
    assert r.json()["new_path"] == "house/b.mp3"
    assert (roots["audio"] / "house/b.mp3").exists()
    assert main_module.db_get_file("audio", "house/b.mp3")["title"] == "A"
    assert main_module.read_history()["vid00000002"]["audio"] == "house/b.mp3"


def test_rename_rejects_bad_names_and_conflicts(client, roots):
    touch(roots["audio"] / "a.mp3")
    touch(roots["audio"] / "b.mp3")
    bad = ["../x", "sub/x", ".hidden", "", "///"]
    for name in bad:
        r = client.post("/file/rename", json={"root": "audio", "old_path": "a.mp3", "new_name": name})
        assert r.status_code == 400, name
    r = client.post("/file/rename", json={"root": "audio", "old_path": "a.mp3", "new_name": "b.mp3"})
    assert r.status_code == 409
    assert client.post("/file/rename", json={"root": "audio", "old_path": "zzz.mp3", "new_name": "q"}).status_code == 404


def test_move(client, roots, main_module):
    touch(roots["audio"] / "house/a.mp3")
    main_module.db_upsert_file("audio", "house/a.mp3")
    r = client.post("/file/move", json={"root": "audio", "old_path": "house/a.mp3", "new_dir": "techno/deep"})
    assert r.json() == {"ok": True, "new_path": "techno/deep/a.mp3", "moved": True}
    assert (roots["audio"] / "techno/deep/a.mp3").exists()
    assert main_module.db_get_file("audio", "techno/deep/a.mp3") is not None

    # move to root
    r = client.post("/file/move", json={"root": "audio", "old_path": "techno/deep/a.mp3", "new_dir": ""})
    assert r.json()["new_path"] == "a.mp3"
    # no-op
    assert client.post("/file/move", json={"root": "audio", "old_path": "a.mp3", "new_dir": ""}).json()["moved"] is False
    # conflict
    touch(roots["audio"] / "house/a.mp3")
    assert client.post("/file/move", json={"root": "audio", "old_path": "a.mp3", "new_dir": "house"}).status_code == 409
    # traversal
    assert client.post("/file/move", json={"root": "audio", "old_path": "a.mp3", "new_dir": "../out"}).status_code == 400


def test_check_prunes_stale_history(client, roots, main_module):
    touch(roots["audio"] / "a.mp3")
    main_module.record_download("dQw4w9WgXcQ", "audio", "a.mp3")
    main_module.record_download("dQw4w9WgXcQ", "video", "gone.mp4")
    r = client.get("/check", params={"url": "https://youtu.be/dQw4w9WgXcQ"})
    assert r.json() == {"video_id": "dQw4w9WgXcQ", "audio": "a.mp3", "video": None}
    assert main_module.read_history()["dQw4w9WgXcQ"] == {"audio": "a.mp3"}
    assert client.get("/check", params={"url": "https://example.com"}).json()["video_id"] is None
