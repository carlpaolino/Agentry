"""Per-client folders and the registry. Every stage gets its client folder from here.

clients/
  registry.json                 {slug: {slug, website, business_name, vertical, status, agent_id, updated_at}}
  <slug>/
    source/pages/*.md           crawl
    source/pages.json           crawl  [{"url", "file"}]
    profile.json                extract
    pricing.json                extract (draft) -> review (approved)
    policy.json                 review
    answers.json                review (raw operator answers)
    agent/prompt.md             prompt
    agent/first_message.txt     prompt
    agent/agent.json            deploy  {"agent_id"}
    agent/voiceflow.json        voiceflow_deploy  {"project_id"}
    agent/voiceflow_snippet.html  voiceflow_deploy  (embed <script> for the website)
    agent/chat_preview.html     voiceflow_deploy  (local demo page)
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Type, TypeVar
from urllib.parse import urlparse

from pydantic import BaseModel

CLIENTS_DIR = Path("clients")
REGISTRY = CLIENTS_DIR / "registry.json"
M = TypeVar("M", bound=BaseModel)


def slug_for(url: str) -> str:
    host = urlparse(url if "://" in url else f"https://{url}").netloc.lower()
    host = host.split(":")[0].removeprefix("www.")
    name = host.rsplit(".", 1)[0]
    return re.sub(r"[^a-z0-9]+", "-", name).strip("-")


def client_dir(slug: str) -> Path:
    d = CLIENTS_DIR / slug
    (d / "source" / "pages").mkdir(parents=True, exist_ok=True)
    (d / "agent").mkdir(parents=True, exist_ok=True)
    return d


def load_registry() -> dict:
    return json.loads(REGISTRY.read_text()) if REGISTRY.exists() else {}


def get_client(slug: str) -> Optional[dict]:
    return load_registry().get(slug)


def upsert(slug: str, **fields) -> dict:
    reg = load_registry()
    rec = reg.get(slug, {"slug": slug})
    rec.update({k: v for k, v in fields.items() if v is not None})
    rec["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    reg[slug] = rec
    CLIENTS_DIR.mkdir(exist_ok=True)
    REGISTRY.write_text(json.dumps(reg, indent=2, sort_keys=True))
    return rec


def save_model(path: Path, obj: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(obj.model_dump_json(indent=2))


def load_model(path: Path, model: Type[M]) -> M:
    return model.model_validate_json(path.read_text())
