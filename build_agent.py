"""Company URL -> ElevenLabs agent, organized per client.

    python build_agent.py https://somehvac.com                        # new client, all stages
    python build_agent.py --client somehvac --from-stage prompt       # rerun from a stage
    python build_agent.py --client somehvac --from-stage extract --to-stage extract   # one stage
    python build_agent.py https://somehvac.com --demo                 # cold-call demo: no review, no prices
    python build_agent.py --list                                      # all clients and their status
"""
import argparse
import sys

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

import clients
import crawl
import demo
import deploy
import extract
import prompt_builder
import review

STAGES = ["crawl", "extract", "review", "prompt", "deploy"]
DONE = {"crawl": "crawled", "extract": "extracted", "review": "reviewed",
        "prompt": "prompted", "deploy": "deployed"}
console = Console()


def print_registry() -> None:
    t = Table("slug", "business", "vertical", "status", "agent_id", "updated")
    for r in clients.load_registry().values():
        t.add_row(r["slug"], r.get("business_name", ""), r.get("vertical", ""),
                  r.get("status", ""), r.get("agent_id", ""), r.get("updated_at", ""))
    console.print(t)


def main() -> None:
    load_dotenv(".env")
    p = argparse.ArgumentParser()
    p.add_argument("url", nargs="?")
    p.add_argument("--client", help="existing client slug")
    p.add_argument("--from-stage", choices=STAGES, default="crawl")
    p.add_argument("--to-stage", choices=STAGES, default="deploy")
    p.add_argument("--demo", action="store_true", help="skip review: website facts only, no prices")
    p.add_argument("--list", action="store_true")
    args = p.parse_args()

    if args.list:
        print_registry()
        return

    if args.url:
        slug = clients.slug_for(args.url)
        clients.upsert(slug, website=args.url)
    elif args.client:
        slug = args.client
    else:
        sys.exit("Give a URL or --client <slug>")

    rec = clients.get_client(slug) or {}
    cdir = clients.client_dir(slug)
    start = STAGES.index(args.from_stage)
    end = STAGES.index(args.to_stage)
    if end < start:
        sys.exit("--to-stage comes before --from-stage")

    for stage in STAGES[start:end + 1]:
        console.print(f"[bold]>> {stage}[/bold]  ({slug})")
        if stage == "crawl":
            if not rec.get("website"):
                sys.exit("No website for this client; pass the URL.")
            crawl.run(rec["website"], cdir)
        elif stage == "extract":
            extract.run(cdir)
        elif stage == "review":
            if args.demo:
                demo.prepare(cdir)
            else:
                review.run(cdir)
                clients.upsert(slug, mode="live")
        elif stage == "prompt":
            prompt_builder.run(cdir)
        elif stage == "deploy":
            deploy.run(cdir)
        clients.upsert(slug, status=DONE[stage])

    console.print(f"[green]Done: {slug}[/green]")


if __name__ == "__main__":
    main()
