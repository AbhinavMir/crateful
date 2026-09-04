import json


def test_parse_json_config(home, main_module):
    (home / "config.json").write_text(json.dumps({"provider": "openai", "model": "gpt-x"}))
    assert main_module._parse_config_file() == {"provider": "openai", "model": "gpt-x"}


def test_parse_env_style_config(home, main_module):
    (home / "config.json").write_text(
        '# comment\nANTHROPIC_API_KEY="sk-ant-1"\nprovider=ollama\n\nbad line\n'
    )
    assert main_module._parse_config_file() == {
        "ANTHROPIC_API_KEY": "sk-ant-1",
        "provider": "ollama",
    }


def test_missing_or_empty_config(home, main_module):
    (home / "config.json").write_text("")
    assert main_module._parse_config_file() == {}
    (home / "config.json").unlink()
    assert main_module._parse_config_file() == {}


def test_read_config_defaults(home, main_module):
    (home / "config.json").write_text("{}")
    cfg = main_module.read_config()
    assert cfg["provider"] == "anthropic"
    assert cfg["model"] == main_module.DEFAULT_MODEL_BY_PROVIDER["anthropic"]
    assert cfg["anthropic_api_key"] is None
    assert cfg["ollama_url"] == main_module.DEFAULT_OLLAMA_URL


def test_unknown_provider_falls_back(home, main_module):
    (home / "config.json").write_text(json.dumps({"provider": "gemini"}))
    assert main_module.read_config()["provider"] == "anthropic"


def test_env_overrides_file(home, main_module, monkeypatch):
    (home / "config.json").write_text(
        json.dumps({"provider": "anthropic", "anthropic_api_key": "file-key", "model": "m1"})
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    monkeypatch.setenv("YTD_PROVIDER", "openai")
    monkeypatch.setenv("YTD_MODEL", "m2")
    cfg = main_module.read_config()
    assert cfg["anthropic_api_key"] == "env-key"
    assert cfg["provider"] == "openai"
    assert cfg["model"] == "m2"


def test_active_api_key_per_provider(home, main_module):
    (home / "config.json").write_text(
        json.dumps({"provider": "openai", "openai_api_key": "oa", "anthropic_api_key": "an"})
    )
    assert main_module.active_api_key() == "oa"
    (home / "config.json").write_text(json.dumps({"provider": "ollama", "openai_api_key": "oa"}))
    assert main_module.active_api_key() is None


def test_put_config_writes_and_clears(client, home):
    r = client.put("/config", json={"provider": "OpenAI", "model": "gpt-4o-mini"})
    assert r.status_code == 200
    saved = json.loads((home / "config.json").read_text())
    assert saved["provider"] == "openai"
    assert saved["model"] == "gpt-4o-mini"

    r = client.put("/config", json={"model": ""})
    assert r.status_code == 200
    saved = json.loads((home / "config.json").read_text())
    assert "model" not in saved


def test_put_config_rejects_bad_provider(client):
    assert client.put("/config", json={"provider": "gemini"}).status_code == 400


def test_get_config_never_returns_keys(client, home, roots):
    cfg = json.loads((home / "config.json").read_text())
    cfg["anthropic_api_key"] = "sk-ant-secret"
    (home / "config.json").write_text(json.dumps(cfg))
    body = client.get("/config").text
    assert "sk-ant-secret" not in body
    assert client.get("/config").json()["has_anthropic_key"] is True


def test_status_reports_key_presence(client, home, roots):
    cfg = json.loads((home / "config.json").read_text())
    cfg["provider"] = "ollama"
    (home / "config.json").write_text(json.dumps(cfg))
    assert client.get("/status").json()["has_api_key"] is True  # ollama needs no key
    cfg["provider"] = "anthropic"
    (home / "config.json").write_text(json.dumps(cfg))
    assert client.get("/status").json()["has_api_key"] is False


# --- cookies from browser ---------------------------------------------------

def test_cookie_browser_defaults_to_off(home, main_module):
    (home / "config.json").write_text("{}")
    assert main_module.read_config()["cookies_from_browser"] == ""
    assert "cookiesfrombrowser" not in main_module.ydl_opts()


def test_cookie_browser_is_passed_to_yt_dlp(home, main_module):
    (home / "config.json").write_text(json.dumps({"cookies_from_browser": "Chrome"}))
    assert main_module.read_config()["cookies_from_browser"] == "chrome"
    assert main_module.ydl_opts()["cookiesfrombrowser"] == ("chrome",)


def test_unknown_cookie_browser_is_ignored(home, main_module):
    (home / "config.json").write_text(json.dumps({"cookies_from_browser": "netscape"}))
    assert main_module.read_config()["cookies_from_browser"] == ""


def test_put_config_rejects_unknown_browser(client):
    r = client.put("/config", json={"cookies_from_browser": "netscape"})
    assert r.status_code == 400


def test_ydl_opts_keeps_the_base_settings(main_module):
    opts = main_module.ydl_opts(skip_download=True)
    assert opts["noplaylist"] is True
    assert opts["quiet"] is True
    assert opts["skip_download"] is True


def test_bot_error_points_at_the_setting(main_module):
    msg = main_module.friendly_ydl_error(
        RuntimeError("ERROR: [youtube] abc: Sign in to confirm you're not a bot. Use --cookies-from-browser"))
    assert "Settings" in msg
    assert "not a bot" not in msg
    plain = main_module.friendly_ydl_error(RuntimeError("Video unavailable"))
    assert plain == "Video unavailable"
