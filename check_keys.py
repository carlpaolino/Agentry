"""Make one cheap call per service to confirm the keys in .env work.

Usage: python check_keys.py
Prints one line per service ("OK" or "FAILED: <error>") and exits non-zero if any fail.
"""
import os
import sys

from dotenv import load_dotenv
from rich.console import Console

console = Console(highlight=False, soft_wrap=True)
KEY_NAMES = ["ANTHROPIC_API_KEY", "FIRECRAWL_API_KEY", "ELEVENLABS_API_KEY"]


def require(name):
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is not set in .env")
    return value


def redact(text):
    for name in KEY_NAMES:
        value = os.getenv(name)
        if value:
            text = text.replace(value, "<redacted>")
    return text


def check_anthropic():
    import anthropic

    client = anthropic.Anthropic(api_key=require("ANTHROPIC_API_KEY"))
    client.messages.create(
        model="claude-haiku-5-5",
        max_tokens=5,
        messages=[{"role": "user", "content": "say ok"}],
    )


def check_firecrawl():
    from firecrawl import Firecrawl

    doc = Firecrawl(api_key=require("FIRECRAWL_API_KEY")).scrape(
        "https://example.com", formats=["markdown"]
    )
    if not getattr(doc, "markdown", None):
        raise RuntimeError("scrape returned no markdown")


def check_elevenlabs():
    from elevenlabs.client import ElevenLabs

    client = ElevenLabs(api_key=require("ELEVENLABS_API_KEY"))
    client.voices.get(voice_id=require("ELEVENLABS_VOICE_ID"))


def main():
    load_dotenv(".env")
    checks = [
        ("Anthropic", check_anthropic),
        ("Firecrawl", check_firecrawl),
        ("ElevenLabs", check_elevenlabs),
    ]
    failed = False
    for name, check in checks:
        try:
            check()
            console.print(f"{name}: [green]OK[/green]")
        except Exception as e:
            failed = True
            if hasattr(e, "status_code") and hasattr(e, "body"):
                message = f"HTTP {e.status_code}: {e.body}"
            else:
                message = f"{type(e).__name__}: {e}"
            message = redact(message).splitlines()[0][:300]
            console.print(f"{name}: [red]FAILED:[/red] ", end="")
            console.print(message, markup=False)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
