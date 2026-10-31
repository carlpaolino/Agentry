"""Stage 4 - prompt: profile + policy + pricing -> the agent's instructions.

run(cdir):
  - Load profile.json, policy.json, pricing.json.
  - Render templates/base.md with string.Template.substitute (NOT format; prices contain "$").
    $emergency_rules comes from templates/emergencies/<vertical>.md (fallback hvac.md).
  - $price_list: ONLY items with approved=True, one bullet each, e.g.
    "- Water heater install: $1,200 to $2,400 per job (tank units only)". If share_prices is False
    or nothing is approved: "No prices are approved. Never give a price; say the team will quote."
  - Any blank value renders as "Not listed. Say the team will confirm."
  - Fail loudly if any "$name" placeholder is left in the output.
  - Write cdir/agent/prompt.md and cdir/agent/first_message.txt.
"""
from pathlib import Path


def run(cdir: Path) -> None:
    raise NotImplementedError("prompt: see CURSOR_PROMPTS.md, Prompt 5")
