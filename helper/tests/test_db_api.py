from conftest import touch


def test_db_file_creates_record_on_demand(client, roots):
    touch(roots["audio"] / "a.mp3")
    r = client.get("/db/file", params={"root": "audio", "path": "a.mp3"})
    assert r.status_code == 200
    body = r.json()
    assert body["rel_path"] == "a.mp3"
    assert body["position_sec"] == 0
    assert body["completed"] is False
    assert client.get("/db/file", params={"root": "audio", "path": "missing.mp3"}).status_code == 404
    assert client.get("/db/file", params={"root": "bad", "path": "a.mp3"}).status_code == 400


def test_position_and_continue_listening(client, roots):
    touch(roots["audio"] / "a.mp3")
    touch(roots["audio"] / "b.mp3")
    r = client.post("/db/position", json={"root": "audio", "path": "a.mp3", "position_sec": 42.5, "duration_sec": 300})
    assert r.status_code == 200
    rec = client.get("/db/file", params={"root": "audio", "path": "a.mp3"}).json()
    assert rec["position_sec"] == 42.5
    assert rec["duration_sec"] == 300

    items = client.get("/db/continue", params={"root": "audio"}).json()["items"]
    assert [i["rel_path"] for i in items] == ["a.mp3"]

    # negative positions clamp to 0 and drop out of continue-listening
    client.post("/db/position", json={"root": "audio", "path": "a.mp3", "position_sec": -5})
    assert client.get("/db/continue", params={"root": "audio"}).json()["items"] == []

    assert client.post("/db/position", json={"root": "audio", "path": "zzz.mp3", "position_sec": 1}).status_code == 404


def test_completed_toggles_and_counts_plays(client, roots):
    touch(roots["audio"] / "a.mp3")
    client.post("/db/position", json={"root": "audio", "path": "a.mp3", "position_sec": 10})
    assert client.post("/db/completed", json={"root": "audio", "path": "a.mp3"}).status_code == 200
    rec = client.get("/db/file", params={"root": "audio", "path": "a.mp3"}).json()
    assert rec["completed"] is True
    assert rec["play_count"] == 1
    assert client.get("/db/continue", params={"root": "audio"}).json()["items"] == []

    client.post("/db/completed", json={"root": "audio", "path": "a.mp3", "completed": False})
    rec = client.get("/db/file", params={"root": "audio", "path": "a.mp3"}).json()
    assert rec["completed"] is False
    assert rec["play_count"] == 1


def test_browse_attaches_playback_state(client, roots):
    touch(roots["audio"] / "a.mp3")
    client.post("/db/position", json={"root": "audio", "path": "a.mp3", "position_sec": 7, "duration_sec": 70})
    files = client.get("/browse", params={"root": "audio", "path": ""}).json()["files"]
    assert files[0]["playback"]["position_sec"] == 7
    assert files[0]["playback"]["duration_sec"] == 70


def test_backfill_adds_disk_files(client, roots, main_module):
    touch(roots["audio"] / "x/a.mp3")
    touch(roots["video"] / "v.mp4")
    touch(roots["audio"] / "ignored.txt")
    assert client.post("/db/backfill").json()["added"] == 2
    assert client.post("/db/backfill").json()["added"] == 0
    assert main_module.db_get_file("audio", "x/a.mp3") is not None
    assert main_module.db_get_file("video", "v.mp4") is not None
