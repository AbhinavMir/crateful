"""Only the extension and youtube.com content script may call the helper from a browser."""

GOOD_EXT = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
GOOD_YT = "https://www.youtube.com"


def test_no_origin_header_is_allowed(client):
    assert client.get("/status").status_code == 200


def test_extension_origin_allowed(client):
    r = client.get("/status", headers={"Origin": GOOD_EXT})
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == GOOD_EXT


def test_youtube_origin_allowed(client):
    r = client.get("/status", headers={"Origin": GOOD_YT})
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == GOOD_YT


def test_random_site_is_rejected(client):
    r = client.get("/status", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert "access-control-allow-origin" not in r.headers


def test_random_site_cannot_mutate(client, roots):
    (roots["audio"] / "x.mp3").write_bytes(b"\x00")
    r = client.delete("/file", params={"root": "audio", "path": "x.mp3"},
                      headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert (roots["audio"] / "x.mp3").exists()


def test_lookalike_origins_rejected(client):
    for origin in (
        "https://www.youtube.com.evil.example",
        "http://www.youtube.com",
        "https://evil.example/https://www.youtube.com",
        "chrome-extension://short",
        "null",
    ):
        r = client.get("/status", headers={"Origin": origin})
        assert r.status_code == 403, origin


def test_preflight_from_bad_origin_gets_no_cors(client):
    r = client.options(
        "/file",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "DELETE",
        },
    )
    assert r.status_code == 403
    assert "access-control-allow-origin" not in r.headers


def test_preflight_from_extension_ok(client):
    r = client.options(
        "/file",
        headers={
            "Origin": GOOD_EXT,
            "Access-Control-Request-Method": "DELETE",
        },
    )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == GOOD_EXT
