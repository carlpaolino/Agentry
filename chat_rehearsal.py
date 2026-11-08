"""Rehearse the website chat agent in the terminal, without Voiceflow.

python chat_rehearsal.py --client <slug>
  - Loads clients/<slug>/agent/chat_instructions.md as the system prompt for claude-haiku-5-5.
  - Prints the opening line (from the instructions' 'Start every new chat with: "..."' line) first,
    then alternates visitor input / agent reply. "quit" (or end of input) stops.
  - Saves the transcript to clients/<slug>/rehearsals/<timestamp>.md after every turn.
"""
import argparse
import os
import re
import sys
from datetime import datetime

import anthropic
from dotenv import load_dotenv
from rich.console import Console
from rich.markup import escape

import clients

MODEL = "claude-haiku-5-5"
OPENED = "[The visitor opened the chat window on the website.]"
console = Console(highlight=False, soft_wrap=True)


def fail(message: str) -> None:
    console.print(f"[red]rehearsal failed:[/red] {escape(message)}")
    sys.exit(1)


def opening_line(instructions: str) -> str:
    m = re.match(r'Start every new chat with: "(.+)"', instructions.strip().splitlines()[0])
    if not m:
        fail('chat_instructions.md does not start with: Start every new chat with: "..."')
    return m.group(1)


def save(path, slug: str, turns: list) -> None:
    lines = [f"# Chat rehearsal: {slug}", "", f"{datetime.now():%Y-%m-%d %H:%M} · {MODEL}", ""]
    for role, text in turns:
        lines += [f"**{role}:** {text}", ""]
    path.write_text("\n".join(lines))


def main() -> None:
    ap = argparse.ArgumentParser(description="Rehearse the website chat agent in the terminal.")
    ap.add_argument("--client", required=True, help="client slug, e.g. empirehvac")
    slug = ap.parse_args().client
    load_dotenv(".env")
    if not clients.get_client(slug):
        fail(f"no client '{slug}' in the registry")
    cdir = clients.client_dir(slug)
    path = cdir / "agent" / "chat_instructions.md"
    if not path.exists():
        fail(f"{path} not found; build the chat channel first")
    instructions = path.read_text()
    first = opening_line(instructions)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        fail("ANTHROPIC_API_KEY is not set")
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    out_dir = cdir / "rehearsals"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{datetime.now():%Y%m%d-%H%M%S}.md"
    messages = [{"role": "user", "content": OPENED}, {"role": "assistant", "content": first}]
    turns = [("Agent", first)]
    save(out, slug, turns)
    console.print(f"[dim]Rehearsing {slug} with {MODEL}. Type quit to stop. Saving to {out}[/dim]")
    console.print(f"[bold cyan]Agent:[/bold cyan] {escape(first)}")
    while True:
        try:
            text = input("You: ").strip()
        except EOFError:
            break
        if text.lower() == "quit":
            break
        if not text:
            continue
        if not sys.stdin.isatty():
            console.print(f"[dim](typed)[/dim] {escape(text)}")
        messages.append({"role": "user", "content": text})
        try:
            resp = client.messages.create(model=MODEL, max_tokens=800, system=instructions, messages=messages)
        except anthropic.APIError as e:
            fail(f"Claude call failed: {e}")
        reply = "".join(b.text for b in resp.content if b.type == "text").strip()
        messages.append({"role": "assistant", "content": reply})
        turns += [("Visitor", text), ("Agent", reply)]
        save(out, slug, turns)
        console.print(f"[bold cyan]Agent:[/bold cyan] {escape(reply)}")
    console.print(f"[green]Saved transcript:[/green] {out} ({(len(turns) - 1) // 2} visitor turns)")


if __name__ == "__main__":
    main()
