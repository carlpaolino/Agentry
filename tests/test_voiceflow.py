"""voiceflow_deploy against a fake Voiceflow (httpx.MockTransport). No network, no real key."""
import json

import httpx
import pytest

import voiceflow_deploy as vf

TOKEN = "vfp_test_secret_token"
SNIPPET = '<script src="https://cdn.voiceflow.com/widget/bundle.mjs"></script>'


class FakeVoiceflow:
    """Answers each API entry with the documented shape; set .fail[name] = (status, body) to break one."""

    def __init__(self):
        self.calls = []        # [(api name, request)]
        self.fail = {}
        self.unresolved = {}

    def route(self, request: httpx.Request) -> str:
        for name, spec in vf.API.items():
            if not isinstance(spec, dict) or "method" not in spec or spec["method"] != request.method:
                continue
            parts, want = request.url.path.split("/"), spec["path"].split("/")
            if len(parts) == len(want) and all(w.startswith("{") or w == p for p, w in zip(parts, want)):
                return name
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    def __call__(self, request: httpx.Request) -> httpx.Response:
        name = self.route(request)
        self.calls.append((name, request))
        if name in self.fail:
            status, body = self.fail[name]
            return httpx.Response(status, json=body)
        body = {
            "get_workspace": {"workspace": {"id": "ws1", "name": "Test Workspace"}},
            "list_workspaces": {"workspaces": [{"id": "ws1", "name": "Test Workspace"}]},
            "create_project": {"project": {"id": "proj123", "name": "x"}},
            "environments": {"environments": [{"alias": "staging", "isMain": False},
                                              {"alias": "main", "isMain": True}]},
            "set_prompt": {"message": "updated", **self.unresolved},
            "compile": {"message": "compiled", "durationMs": 12},
            "publish": {"environment": {}, "release": {"name": "x"}},
            "snippet": {"snippet": SNIPPET},
        }[name]
        return httpx.Response(vf.API[name]["status"], json=body)

    def names(self) -> list[str]:
        return [n for n, _ in self.calls]


@pytest.fixture
def cdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)            # registry lookups read tmp_path/clients, not the real one
    monkeypatch.setenv("VOICEFLOW_API_KEY", TOKEN)
    monkeypatch.setenv("VOICEFLOW_WORKSPACE_ID", "ws1")
    d = tmp_path / "clients" / "testco"
    d.mkdir(parents=True)
    return d


def test_first_run_creates_and_publishes(cdir):
    fake = FakeVoiceflow()
    vf.run(cdir, "Be helpful.", "Hi there!", transport=httpx.MockTransport(fake))

    assert fake.names() == ["get_workspace", "create_project", "environments", "set_prompt",
                            "compile", "publish", "snippet"]
    req = dict(fake.calls)
    assert req["create_project"].headers["Authorization"] == f"Bearer {TOKEN}"
    assert json.loads(req["create_project"].content) == {
        "name": "testco - Website Assistant", "workspaceID": "ws1", "type": "webchat"}
    assert req["set_prompt"].url.params["projectID"] == "proj123"
    assert req["set_prompt"].url.params["environmentAlias"] == "main"
    sent = json.loads(req["set_prompt"].content)["prompt"]
    assert sent.startswith('Start every new chat with: "Hi there!"') and sent.endswith("Be helpful.")
    assert req["publish"].url.path == "/v1/stable/environment/main/publish"
    assert json.loads(req["publish"].content)["name"].startswith("build ")
    assert req["snippet"].url.params["version"] == "published"

    agent = cdir / "agent"
    assert json.loads((agent / "voiceflow.json").read_text()) == {"project_id": "proj123"}
    assert SNIPPET in (agent / "voiceflow_snippet.html").read_text()
    assert SNIPPET in (agent / "chat_preview.html").read_text()


def test_second_run_reuses_project(cdir):
    (cdir / "agent").mkdir()
    (cdir / "agent" / "voiceflow.json").write_text(json.dumps({"project_id": "proj123"}))
    fake = FakeVoiceflow()
    vf.run(cdir, "Be helpful.", "Hi there!", transport=httpx.MockTransport(fake))

    assert "create_project" not in fake.names() and "get_workspace" not in fake.names()
    assert fake.names() == ["environments", "set_prompt", "compile", "publish", "snippet"]
    assert dict(fake.calls)["set_prompt"].url.params["projectID"] == "proj123"


def test_unresolved_references_fail_before_publish(cdir, capsys):
    fake = FakeVoiceflow()
    fake.unresolved = {"unresolvedReferences": [{"path": "prompt", "name": "first_name"}]}
    with pytest.raises(SystemExit) as e:
        vf.run(cdir, "Hi {first_name}", "Hi!", transport=httpx.MockTransport(fake))

    assert e.value.code == 1
    assert "publish" not in fake.names() and "compile" not in fake.names()
    out = capsys.readouterr().out
    assert "NOT published" in out and "first_name" in out


def test_401_prints_clear_error_without_token(cdir, capsys):
    fake = FakeVoiceflow()
    fake.fail["get_workspace"] = (401, {"message": f"invalid token {TOKEN}"})
    with pytest.raises(SystemExit) as e:
        vf.run(cdir, "Be helpful.", "Hi!", transport=httpx.MockTransport(fake))

    assert e.value.code == 1
    out = capsys.readouterr().out
    assert "GET /v1/stable/workspace/ws1 -> HTTP 401" in out
    assert "VOICEFLOW_API_KEY" in out
    assert TOKEN not in out
    assert not (cdir / "agent" / "voiceflow.json").exists()


def test_list_workspaces(cdir, capsys):
    vf.list_workspaces(transport=httpx.MockTransport(FakeVoiceflow()))
    assert "ws1  Test Workspace" in capsys.readouterr().out


def test_list_workspaces_unknown_shape_prints_raw(cdir, capsys):
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"data": {"items": []}}))
    vf.list_workspaces(transport=transport)
    assert '"items"' in capsys.readouterr().out
