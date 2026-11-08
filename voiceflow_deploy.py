"""Chat channel - deploy: create or update this client's Voiceflow web-chat agent.

export_pack(cdir, prompt, first_message): writes agent/chat_instructions.md and agent/voiceflow_setup.md
  (manual steps), every time, with or without a key.

run(cdir, prompt, first_message):
  - prompt/first_message come from prompt_builder.render(..., channel="chat").
  - httpx against https://realtime-api.voiceflow.com, "Authorization: Bearer <VOICEFLOW_API_KEY>".
  - No cdir/agent/voiceflow.json yet: POST /v1/stable/project {"name": "<Business> - Website Assistant",
    "workspaceID": VOICEFLOW_WORKSPACE_ID, "type": "webchat"} and save {"project_id": ...} there.
  - Every run: main environment (isMain) -> PATCH /v2/stable/agent {"prompt": ...} (the opening line goes
    in the prompt; fail on unresolvedReferences/unresolvedMentions) -> compile -> publish -> snippet.
  - Writes agent/voiceflow_snippet.html and agent/chat_preview.html (open it locally for demos).
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

BASE = "https://realtime-api.voiceflow.com"
console = Console(highlight=False, soft_wrap=True)


def fail(message: str) -> None:
    console.print(f"[red]voiceflow deploy failed:[/red] {escape(message)}")
    sys.exit(1)


def call(http: httpx.Client, method: str, path: str, ok: int, **kwargs) -> dict:
    try:
        r = http.request(method, path, **kwargs)
    except httpx.HTTPError as e:
        fail(f"{method} {path}: {e}")
    if r.status_code != ok:
        fail(f"{method} {path} -> HTTP {r.status_code}: {r.text}")
    return r.json()


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


def run(cdir: Path, prompt: str, first_message: str) -> None:
    for name in ("VOICEFLOW_API_KEY", "VOICEFLOW_WORKSPACE_ID"):
        if not os.getenv(name):
            fail(f"{name} is not set in .env")
    slug = cdir.name
    agent_dir = cdir / "agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    vf_json = agent_dir / "voiceflow.json"
    rec = clients.get_client(slug) or {}
    business_name = rec.get("business_name") or slug

    headers = {"Authorization": f"Bearer {os.environ['VOICEFLOW_API_KEY']}"}
    with httpx.Client(base_url=BASE, headers=headers, timeout=60) as http:
        project_id = json.loads(vf_json.read_text()).get("project_id") if vf_json.exists() else None
        if project_id:
            console.print(f"Using project {project_id}")
        else:
            ws_id = os.environ["VOICEFLOW_WORKSPACE_ID"]
            ws = call(http, "GET", f"/v1/stable/workspace/{ws_id}", 200)
            console.print(f"Workspace: {ws.get('workspace', {}).get('name', ws_id)}")
            name = f"{business_name} - Website Assistant"
            project_id = call(http, "POST", "/v1/stable/project", 201,
                              json={"name": name, "workspaceID": ws_id, "type": "webchat"})["project"]["id"]
            vf_json.write_text(json.dumps({"project_id": project_id}, indent=2))
            console.print(f"Created project {project_id} ({name})")
        q = {"projectID": project_id}

        envs = call(http, "GET", "/v1/stable/environment", 200, params=q)["environments"]
        main = next((e for e in envs if e.get("isMain")), None)
        if main is None:
            fail(f"project {project_id} has no main environment: {[e.get('alias') for e in envs]}")
        alias = main["alias"]

        full_prompt = chat_instructions(prompt, first_message)
        res = call(http, "PATCH", "/v2/stable/agent", 200, params={**q, "environmentAlias": alias},
                   json={"prompt": full_prompt})
        unresolved = res.get("unresolvedReferences") or []
        mentions = res.get("unresolvedMentions") or []
        if unresolved or mentions:
            fail(f"prompt saved to the draft but NOT published; unresolved references {unresolved}, "
                 f"mentions {mentions}")
        console.print(f"Set the prompt on '{alias}' ({len(full_prompt):,} chars)")

        call(http, "PUT", f"/v1/stable/environment/{alias}/compile", 200, params=q)
        console.print("Compiled")
        release = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        call(http, "POST", f"/v1/stable/environment/{alias}/publish", 201, params=q, json={"name": release})
        console.print(f"Published release '{release}'")

        snippet = call(http, "GET", "/v1/stable/widget/snippet", 200,
                       params={**q, "environmentAlias": alias, "version": "published"})["snippet"]

    (agent_dir / "voiceflow_snippet.html").write_text(snippet + "\n")
    title = html.escape(business_name)
    (agent_dir / "chat_preview.html").write_text(
        f"<!doctype html>\n<html><head><meta charset=\"utf-8\"><title>{title} - chat preview</title></head>\n"
        f"<body style=\"font-family: sans-serif; margin: 3rem;\">\n<h1>{title}</h1>\n"
        f"<p>Chat preview. Open the bubble in the corner.</p>\n{snippet}\n</body></html>\n")
    console.print(f"Wrote {agent_dir / 'voiceflow_snippet.html'}")
    console.print(f"Open the chat: {agent_dir / 'chat_preview.html'}")
