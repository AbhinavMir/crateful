import subprocess

import pytest
from conftest import touch


@pytest.fixture
def no_restart(main_module, monkeypatch):
    calls = []
    monkeypatch.setattr(main_module, "schedule_restart", lambda *a, **k: calls.append(True))
    return calls


@pytest.fixture
def fake_run(main_module, monkeypatch):
    """Capture subprocess.run calls made through main._run; script git rev-parse output."""
    state = {"cmds": [], "heads": ["aaaaaaa1", "aaaaaaa1"], "fail": None}

    def run(cmd, **kw):
        state["cmds"].append(cmd)
        if state["fail"] and state["fail"] in " ".join(cmd):
            raise subprocess.CalledProcessError(1, cmd, output="", stderr="boom")
        out = ""
        if cmd[:2] == ["git", "-C"] and "rev-parse" in cmd:
            out = state["heads"].pop(0)
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

    monkeypatch.setattr(main_module.subprocess, "run", run)
    return state


def test_status_reports_yt_dlp_version(client):
    v = client.get("/status").json()["yt_dlp_version"]
    assert isinstance(v, str) and v


def test_update_noop_when_already_current(client, main_module, fake_run, no_restart, monkeypatch):
    monkeypatch.setattr(main_module, "REPO_ROOT", main_module.REPO_ROOT)  # real checkout has .git
    r = client.post("/update")
    assert r.status_code == 200, r.text
    assert r.json()["updated"] is False
    assert r.json()["will_restart"] is False
    assert no_restart == []
    joined = [" ".join(c) for c in fake_run["cmds"]]
    assert any("fetch" in c for c in joined)
    assert any("pull --ff-only" in c for c in joined)
    assert not any("pip" in c for c in joined)


def test_update_refreshes_deps_and_restarts(client, main_module, fake_run, no_restart, monkeypatch, tmp_path):
    fake_run["heads"] = ["aaaaaaa1", "bbbbbbb2"]
    monkeypatch.setattr(main_module, "REQUIREMENTS_STAMP", tmp_path / "stamp")
    r = client.post("/update")
    assert r.json() == {"ok": True, "updated": True, "before": "aaaaaaa", "after": "bbbbbbb", "will_restart": True}
    assert no_restart == [True]
    pip_cmds = [" ".join(c) for c in fake_run["cmds"] if "pip" in c]
    assert any("-r" in c and "requirements.txt" in c for c in pip_cmds)
    assert any(c.endswith("-U yt-dlp") for c in pip_cmds)
    assert (tmp_path / "stamp").read_text().strip()


def test_update_git_failure_is_500(client, main_module, fake_run, no_restart):
    fake_run["fail"] = "pull"
    r = client.post("/update")
    assert r.status_code == 500
    assert "git failed" in r.json()["detail"]
    assert "boom" in r.json()["detail"]
    assert no_restart == []


def test_update_outside_git_checkout(client, main_module, tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "REPO_ROOT", tmp_path)
    r = client.post("/update")
    assert r.status_code == 400
    assert "Not a git checkout" in r.json()["detail"]


def test_update_yt_dlp(client, main_module, fake_run, no_restart, monkeypatch):
    monkeypatch.setattr(main_module, "yt_dlp_version", lambda: "2026.01.01")
    monkeypatch.setattr(main_module, "_installed_version_subprocess", lambda dist: "2026.09.01")
    r = client.post("/update/yt-dlp")
    assert r.json() == {"ok": True, "updated": True, "before": "2026.01.01", "after": "2026.09.01", "will_restart": True}
    assert no_restart == [True]
    assert [" ".join(c) for c in fake_run["cmds"]][-1].endswith("pip install --disable-pip-version-check -q -U yt-dlp")


def test_update_yt_dlp_noop(client, main_module, fake_run, no_restart, monkeypatch):
    monkeypatch.setattr(main_module, "yt_dlp_version", lambda: "2026.09.01")
    monkeypatch.setattr(main_module, "_installed_version_subprocess", lambda dist: "2026.09.01")
    r = client.post("/update/yt-dlp")
    assert r.json()["updated"] is False
    assert no_restart == []


def test_update_yt_dlp_pip_failure(client, main_module, fake_run, no_restart):
    fake_run["fail"] = "pip"
    r = client.post("/update/yt-dlp")
    assert r.status_code == 500
    assert no_restart == []


@pytest.mark.parametrize(
    "system,expected",
    [
        ("Darwin", ["open", "-R", "{file}"]),
        ("Linux", ["xdg-open", "{dir}"]),
    ],
)
def test_reveal_per_platform(client, main_module, roots, monkeypatch, system, expected):
    f = touch(roots["audio"] / "house/a.mp3")
    calls = []
    monkeypatch.setattr(main_module.platform, "system", lambda: system)
    monkeypatch.setattr(main_module.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    r = client.post("/reveal", params={"root": "audio", "path": "house/a.mp3"})
    assert r.status_code == 200, r.text
    want = [x.format(file=str(f.resolve()), dir=str(f.resolve().parent)) for x in expected]
    assert calls == [want]


def test_reveal_unsupported_platform(client, main_module, roots, monkeypatch):
    touch(roots["audio"] / "a.mp3")
    monkeypatch.setattr(main_module.platform, "system", lambda: "Windows")
    r = client.post("/reveal", params={"root": "audio", "path": "a.mp3"})
    assert r.status_code == 501


def test_reveal_missing(client, roots):
    assert client.post("/reveal", params={"root": "audio", "path": "nope.mp3"}).status_code == 404


def test_restart_argv_is_canonical(main_module):
    argv = main_module.restart_argv()
    assert argv[0] == main_module.sys.executable
    assert argv[1].endswith("main.py")
    assert main_module.Path(argv[1]).exists()


def test_port_env_override(main_module, monkeypatch):
    assert main_module.PORT == 7531
