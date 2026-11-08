"""Chat channel - deploy: create or update this client's Voiceflow web-chat agent.

export_pack(cdir, prompt, first_message): writes agent/chat_instructions.md and agent/voiceflow_setup.md
  (manual steps), every time, with or without a key.

run(cdir, prompt, first_message, transport=None):
  - prompt/first_message come from prompt_builder.render(..., channel="chat").
  - httpx against API["base"], "Authorization: Bearer <VOICEFLOW_API_KEY>". transport is passed to
    httpx.Client so tests can use httpx.MockTransport.
  - No cdir/agent/voiceflow.json yet: check the workspace, create the project, save {"project_id": ...}.
  - Every run: main environment (isMain) -> set the prompt (chat_instructions; fail on unresolved
    references/mentions) -> compile -> publish "build <timestamp>" -> snippet.
  - Writes agent/voiceflow_snippet.html and agent/chat_preview.html (open it locally for demos).

list_workspaces(transport=None): prints id and name of every workspace the key can see.

Every path, field name and expected status is in API below; fix them there when the real API differs.
"""
import html
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from rich.console import Console
from rich.markup import escape

import clients

API = {
    "base": "https://realtime-api.voiceflow.com",
    "get_workspace": {"method": "GET", "path": "/v1/stable/workspace/{workspace_id}", "status": 200,
                      "result": "workspace", "name": "name"},
    "list_workspaces": {"method": "GET", "path": "/v1/stable/workspace", "status": 200,
                        "result": "workspaces", "id": "id", "name": "name"},
    "create_project": {"method": "POST", "path": "/v1/stable/project", "status": 201,
                       "name": "name", "workspace": "workspaceID", "type": "type", "type_value": "webchat",
                       "result": "project", "id": "id"},
    "environments": {"method": "GET", "path": "/v1/stable/environment", "status": 200,
                     "result": "environments", "is_main": "isMain", "alias": "alias"},
    "set_prompt": {"method": "PATCH", "path": "/v2/stable/agent", "status": 200, "prompt": "prompt",
                   "unresolved": ["unresolvedReferences", "unresolvedMentions"]},
    "compile": {"method": "PUT", "path": "/v1/stable/environment/{alias}/compile", "status": 200},
    "publish": {"method": "POST", "path": "/v1/stable/environment/{alias}/publish", "status": 201,
                "name": "name"},
    "snippet": {"method": "GET", "path": "/v1/stable/widget/snippet", "status": 200,
                "version": "published", "result": "snippet"},
    "query": {"project": "projectID", "alias": "environmentAlias", "version": "version"},
}
console = Console(highlight=False, soft_wrap=True)


def fail(message: str) -> None:
    token = os.getenv("VOICEFLOW_API_KEY")
    if token:
        message = message.replace(token, "[token]")
    console.print(f"[red]voiceflow deploy failed:[/red] {escape(message)}")
    sys.exit(1)


def client(transport=None) -> httpx.Client:
    if not os.getenv("VOICEFLOW_API_KEY"):
        fail("VOICEFLOW_API_KEY is not set in .env")
    return httpx.Client(base_url=API["base"], timeout=60, transport=transport,
                        headers={"Authorization": f"Bearer {os.environ['VOICEFLOW_API_KEY']}"})


def call(http: httpx.Client, name: str, path_args: dict | None = None, **kwargs) -> dict:
    spec = API[name]
    method, path = spec["method"], spec["path"].format(**(path_args or {}))
    try:
        r = http.request(method, path, **kwargs)
    except httpx.HTTPError as e:
        fail(f"{method} {path}: {e}")
    if r.status_code != spec["status"]:
        hint = " (check VOICEFLOW_API_KEY: wrong, expired or revoked)" if r.status_code == 401 else ""
        fail(f"{method} {path} -> HTTP {r.status_code}{hint}: {r.text}")
    try:
        return r.json()
    except ValueError:
        fail(f"{method} {path} -> HTTP {r.status_code} but the body is not JSON: {r.text[:500]}")


def chat_instructions(prompt: str, first_message: str) -> str:
    return f'Start every new chat with: "{first_message}"\n\n{prompt}'


def export_pack(cdir: Path, prompt: str, first_message: str) -> None:
    """Paste pack for building the chat agent by hand: agent/chat_instructions.md + voiceflow_setup.md."""
    agent_dir = cdir / "agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    business_name = (clients.get_client(cdir.name) or {}).get("business_name") or cdir.name
    instructions = agent_dir / "chat_instructions.md"
    instructions.write_text(chat_instructions(prompt, first_message))
    setup = agent_dir / "voiceflow_setup.md"
    setup.write_text(
        f"# Set up the {business_name} website chat in Voiceflow\n\n"
        f"1. In Voiceflow, create a new web-chat agent named \"{business_name} - Website Assistant\".\n"
        f"2. Open the agent's global prompt and replace it with the whole of chat_instructions.md\n"
        f"   (in this folder). Paste it as is; it contains no {{}} or backticks, which Voiceflow would\n"
        f"   read as references.\n"
        f"3. Publish the agent.\n"
        f"4. Open the widget settings, copy the embed snippet, and paste it into {business_name}'s website\n"
        f"   just before the closing </body> tag of every page the chat should appear on.\n"
        f"5. Open the site, start a chat, and check it greets visitors with the opening line at the top of\n"
        f"   chat_instructions.md.\n")
    console.print(f"Wrote {instructions} ({len(instructions.read_text()):,} chars)")
    console.print(f"Wrote {setup}")


def list_workspaces(transport=None) -> None:
    spec = API["list_workspaces"]
    with client(transport) as http:
        data = call(http, "list_workspaces")
    items = data.get(spec["result"]) if isinstance(data, dict) else data
    if not isinstance(items, list):
        console.print(json.dumps(data, indent=2))
        return
    for w in items:
        console.print(f"{w.get(spec['id'], '?')}  {w.get(spec['name'], '')}")


def run(cdir: Path, prompt: str, first_message: str, transport=None) -> None:
    for name in ("VOICEFLOW_API_KEY", "VOICEFLOW_WORKSPACE_ID"):
        if not os.getenv(name):
            fail(f"{name} is not set in .env")
    slug = cdir.name
    agent_dir = cdir / "agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    vf_json = agent_dir / "voiceflow.json"
    rec = clients.get_client(slug) or {}
    business_name = rec.get("business_name") or slug
    qn = API["query"]

    with client(transport) as http:
        project_id = json.loads(vf_json.read_text()).get("project_id") if vf_json.exists() else None
        if project_id:
            console.print(f"Using project {project_id}")
        else:
            ws_id = os.environ["VOICEFLOW_WORKSPACE_ID"]
            spec = API["get_workspace"]
            ws = call(http, "get_workspace", {"workspace_id": ws_id})
            console.print(f"Workspace: {(ws.get(spec['result']) or {}).get(spec['name'], ws_id)}")
            spec = API["create_project"]
            name = f"{business_name} - Website Assistant"
            body = {spec["name"]: name, spec["workspace"]: ws_id, spec["type"]: spec["type_value"]}
            project_id = call(http, "create_project", json=body)[spec["result"]][spec["id"]]
            vf_json.write_text(json.dumps({"project_id": project_id}, indent=2))
            console.print(f"Created project {project_id} ({name})")
        q = {qn["project"]: project_id}

        spec = API["environments"]
        envs = call(http, "environments", params=q)[spec["result"]]
        main = next((e for e in envs if e.get(spec["is_main"])), None)
        if main is None:
            fail(f"project {project_id} has no main environment: {[e.get(spec['alias']) for e in envs]}")
        alias = main[spec["alias"]]
        qa = {**q, qn["alias"]: alias}

        spec = API["set_prompt"]
        full_prompt = chat_instructions(prompt, first_message)
        res = call(http, "set_prompt", params=qa, json={spec["prompt"]: full_prompt})
        problems = {k: res.get(k) for k in spec["unresolved"] if res.get(k)}
        if problems:
            fail(f"prompt saved to the draft but NOT published; unresolved: {problems}")
        console.print(f"Set the prompt on '{alias}' ({len(full_prompt):,} chars)")

        call(http, "compile", {"alias": alias}, params=q)
        console.print("Compiled")
        release = "build " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        call(http, "publish", {"alias": alias}, params=q, json={API["publish"]["name"]: release})
        console.print(f"Published release '{release}'")

        spec = API["snippet"]
        snippet = call(http, "snippet", params={**qa, qn["version"]: spec["version"]})[spec["result"]]

    (agent_dir / "voiceflow_snippet.html").write_text(snippet + "\n")
    title = html.escape(business_name)
    (agent_dir / "chat_preview.html").write_text(
        f"<!doctype html>\n<html><head><meta charset=\"utf-8\"><title>{title} - chat preview</title></head>\n"
        f"<body style=\"font-family: sans-serif; margin: 3rem;\">\n<h1>{title}</h1>\n"
        f"<p>Chat preview. Open the bubble in the corner.</p>\n{snippet}\n</body></html>\n")
    console.print(f"Wrote {agent_dir / 'voiceflow_snippet.html'}")
    console.print(f"Open the chat: {agent_dir / 'chat_preview.html'}")
