import json

import pytest


def test_parse_json_response_strips_fences(main_module):
    assert main_module._parse_json_response('```json\n{"a": 1}\n```') == {"a": 1}
    assert main_module._parse_json_response('  {"a": 1}  ') == {"a": 1}
    with pytest.raises(json.JSONDecodeError):
        main_module._parse_json_response("not json")


def test_build_prompt_truncates_description(main_module):
    info = {"title": "T", "uploader": "U", "duration": 10, "tags": ["x"] * 30, "description": "d" * 5000}
    msg = main_module.build_categorize_prompt(info, [{"name": "house", "subs": ["deep"]}])
    assert "Title: T" in msg
    assert msg.count("d") < 2200
    assert '"house"' in msg


def test_categorize_dispatches_by_provider(main_module, home, monkeypatch):
    calls = []
    monkeypatch.setattr(main_module, "_categorize_anthropic", lambda m, model, key: calls.append(("anthropic", model, key)) or {})
    monkeypatch.setattr(main_module, "_categorize_openai", lambda m, model, key: calls.append(("openai", model, key)) or {})
    monkeypatch.setattr(main_module, "_categorize_ollama", lambda m, model, url: calls.append(("ollama", model, url)) or {})

    (home / "config.json").write_text(json.dumps({"provider": "anthropic", "anthropic_api_key": "k"}))
    main_module.categorize({}, [])
    assert calls[-1] == ("anthropic", main_module.DEFAULT_MODEL_BY_PROVIDER["anthropic"], "k")

    main_module.categorize({}, [], model_override="  claude-x ")
    assert calls[-1][1] == "claude-x"

    (home / "config.json").write_text(json.dumps({"provider": "openai", "openai_api_key": "o", "model": "gpt-z"}))
    main_module.categorize({}, [])
    assert calls[-1] == ("openai", "gpt-z", "o")

    (home / "config.json").write_text(json.dumps({"provider": "ollama", "ollama_url": "http://h:1"}))
    main_module.categorize({}, [])
    assert calls[-1] == ("ollama", main_module.DEFAULT_MODEL_BY_PROVIDER["ollama"], "http://h:1")


def test_missing_key_is_a_clear_error(main_module):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as e:
        main_module._categorize_anthropic("msg", "model", None)
    assert "key missing" in e.value.detail
    with pytest.raises(HTTPException) as e:
        main_module._categorize_openai("msg", "model", "")
    assert "key missing" in e.value.detail


def test_custom_prompt_override(main_module, home):
    (home / "config.json").write_text(json.dumps({"categorize_prompt": "  "}))
    assert main_module.get_categorize_prompt() == main_module.CATEGORIZE_SYSTEM
    (home / "config.json").write_text(json.dumps({"categorize_prompt": "custom"}))
    assert main_module.get_categorize_prompt() == "custom"
