"""Stage 3 - review: the operator fills gaps, confirms fit rules, approves prices. Target: under 5 minutes.

run(cdir), three parts, all in the terminal with rich.prompt (Enter accepts the shown default):
  A. Missing facts: in plain code, list REQUIRED_PROFILE_FIELDS with status missing + staleness_signals.
     One Claude call phrases them as at most 6 grouped plain-English questions. Answers update
     profile.json with status "operator".
  B. Fit policy: a FIXED questionnaire (no AI), defaults pre-filled from profile.json:
     service ZIPs and cities, services offered / not offered, residential?, commercial?, renters ok?,
     regular hours, emergency service? + hours, typical lead time, callback promise,
     owner transfer number. Save policy.json (FitPolicy).
  C. Pricing: ask "Should the agent share any prices?" -> share_prices. If yes, show each draft
     PriceItem; operator chooses approve / edit / delete; then may add items (source="operator",
     approved=True). Always ask for the trip/diagnostic fee and the financing note. Save pricing.json.
  - Save every raw answer to cdir/answers.json. If policy.json exists, ask "Redo review? (y/N)" and
    return on N.
"""
from pathlib import Path


def run(cdir: Path) -> None:
    raise NotImplementedError("review: see CURSOR_PROMPTS.md, Prompt 4")
