# Cursor Prompts: tonight's build

Paste these into Cursor **Agent mode** one at a time, in order. Don't start the next prompt until
the current one's "Done when" check passes. Commit after each one, so you can roll back if Cursor
breaks something.

The project rules in `.cursor/rules/project.mdc` load automatically. The contract is already written:
`schema.py` (data), `clients.py` (folders and registry), `templates/` (the agent's instructions),
and each stage file's docstring (what to build). Cursor fills in the stage files; it shouldn't redesign them.

---

## Why the agent command changed

Your draft: *"Build an inbound sales agent... check scheduling and see if there is a possibility
of working for that customer... give out some price points."*

As written, that invites three things that can hurt the client's business. The agent could
promise appointments it can't see, quote prices the owner never agreed to, and talk a caller
out of booking. The version built here (in `templates/base.md`) keeps your intent and
puts guardrails on each one:

| You asked for | What the agent does instead | Why |
| --- | --- | --- |
| "Check scheduling" | Asks for the caller's preferred days and time window, gives the usual wait, says the team will confirm | It can't see the calendar, so it never double-books or promises a time |
| "Possibility of working for that customer" | Checks ZIP, then service, then property type, then urgency. Sorts the call as good, maybe or not a fit, and still takes details for "maybe" | The owner decides close calls, so leads aren't lost |
| "Give out price points" | Quotes only owner-approved ranges, always with "technician confirms on site" | One wrong quote costs more than one missed call |
| "Sales agent" | Front-desk tone. Takes details, never pushes, never argues price | Home-service callers book with whoever sounds trustworthy |

Fit factors, in the order the agent asks:
1. **ZIP code**: in the service area? This is the fastest disqualifier.
2. **Service needed**: on the offered list, or the not-offered list?
3. **Property**: home or business, owner or renter (renters may need landlord approval).
4. **Urgency**: emergency, this week, or flexible. Does it match the emergency hours?
5. **Price**: never a disqualifier on its own. Concern is noted, financing is mentioned, and the lead is still captured.

---

## Prompt 0: Setup and key check (10 min)

```
Set up the environment and verify every API key works.

1. Create a venv in .venv and install requirements.txt. Tell me the exact activate command for macOS zsh.
2. git init, commit everything with message "skeleton" (.gitignore already excludes .env and clients/).
3. Create check_keys.py that loads .env and makes one cheap call per service:
   - Anthropic: claude-haiku-5-5, max_tokens 5, "say ok"
   - Firecrawl: scrape https://example.com as markdown
   - ElevenLabs: confirm ELEVENLABS_VOICE_ID exists by fetching that voice
   Print one line per service, "OK" or "FAILED: <error>". Never print a key.
4. Run it and show me the output.
```

**Done when:** all three print OK.

---

## Prompt 1: Deploy on a demo client (45 min)

Starting with deploy gets you to a talking agent fastest, and every later stage builds toward it.

```
Implement deploy.py exactly as its docstring says.

Before running it, create a demo client by hand so deploy has something to ship:
- Use clients.upsert("demo-plumbing", website="https://example.com", business_name="Demo Plumbing Co", vertical="plumbing").
- Write clients/demo-plumbing/agent/prompt.md by filling templates/base.md by hand with
  realistic made-up facts for a plumbing company in Atlanta (ZIPs 30303, 30305, 30308, 30309, 30318;
  residential only; renters ok; 24/7 emergency service; usual wait next business day;
  callback promise "Someone from our team will call you back within one business hour.";
  two approved prices: trip fee $89 flat, water heater install $1,200 to $2,400 per job).
  Insert templates/emergencies/plumbing.md at $emergency_rules.
- Write clients/demo-plumbing/agent/first_message.txt:
  "Thanks for calling Demo Plumbing! I'm the AI assistant. I can help get you taken care of. What's going on?"

Look up the ElevenLabs Python SDK docs for agents.create and agents.update before writing code.
Pick a low-latency LLM from ElevenLabs' supported list and tell me which one you chose.

Then run: python build_agent.py --client demo-plumbing --from-stage deploy
Run it a second time and confirm it UPDATES the same agent instead of creating a new one.
```

**Done when:** the agent shows up in your ElevenLabs dashboard, you can talk to it in the browser
test, the second run keeps the same `agent_id`, and `python build_agent.py --list` shows it deployed.

Quick test: ask "how much is a water heater?" (it should give the range plus the caveat), then
"can you come at 3pm tomorrow?" (it should take your preference, not book you).

---

## Prompt 2: Crawl (45 min)

```
Implement crawl.py exactly as its docstring says.

Look up the current Firecrawl Python SDK (v2) for map and scrape before writing code.
For page picking, use client.messages.parse with a small Pydantic model {urls: list[str]}.
Cap the candidate list sent to Claude at 200 URLs.

Test on a real Atlanta HVAC company website (search for one and tell me which URL you used):
  python build_agent.py <url> --to-stage crawl
Show me the list of pages saved and the first 20 lines of the home page markdown.
Run it again and confirm it skips re-crawling.
```

**Done when:** `clients/<slug>/source/pages/` holds 5–10 readable markdown files, and a rerun says "already crawled".

---

## Prompt 3: Extract (1 hr)

```
Implement extract.py exactly as its docstring says, using
client.messages.parse(model="claude-sonnet-5-5", output_format=ExtractionResult, ...).

The system prompt for extraction must say:
- Use only what the pages state. If a fact isn't there, status "missing", value null.
- Every found value cites the page URL it came from in source_url.
- vertical must be one of: hvac, plumbing, cleaning, other.
- Prices: copy only prices the site states, with low/high/unit/notes, approved=false, source="website". Never estimate a price.
- staleness_signals: footer copyright year before 2025, hours that differ between pages, expired promotions, old notices.

Run it on the client from Prompt 2: python build_agent.py --client <slug> --from-stage extract --to-stage extract
Show me the rich table and the draft pricing items.
```

**Done when:** the table shows most required fields in green, nothing is invented (spot-check 3
values against the website), and `profile.json` and `pricing.json` exist.

---

## Prompt 4: Review (1 hr)

This is the stage that protects the client: nothing reaches a caller until a person has confirmed it.

```
Implement review.py exactly as its docstring says (parts A, B, C).

Details:
- Use rich.prompt (Prompt.ask, Confirm.ask). Every question shows a default the operator can accept with Enter.
- Part A: compute gaps in plain Python; only the wording comes from Claude (claude-haiku-5-5,
  structured output: list of {question, fields}). Max 6 questions.
- Part B defaults: services from profile.json; cities from profile.service_area; ZIPs left for the
  operator to type (comma-separated, validate 5 digits each); emergency_service defaults to True if
  profile.emergency_policy mentions 24/7 or emergency; callback_promise defaults to
  "Someone from our team will call you back within one business hour.";
  owner_transfer_number: validate E.164 like +14045551234, allow blank.
- Part C: show draft prices in a numbered rich table; operator types numbers to approve, "e 2" to edit,
  "d 3" to delete, "a" to add, Enter to finish. Added items are source="operator", approved=True.
- Print a final summary: fit rules, approved prices, anything still missing.

Run it on the same client. I'll answer the questions.
```

**Done when:** you can finish review in under 5 minutes, and `policy.json`, `pricing.json` (with
approved items) and `answers.json` are saved. A rerun asks "Redo review?".

---

## Prompt 5: Prompt builder (45 min)

```
Implement prompt_builder.py exactly as its docstring says.

templates/base.md uses these placeholders. Fill every one:
business_name, vertical, main_phone, regular_hours, emergency_line, service_zips, service_cities,
services_offered, services_not_offered, property_types, typical_lead_time, financing_note,
licensed_insured, brands_serviced, warranty, payment_methods, faqs, callback_promise,
renters_note, price_list, quote_rule, emergency_rules, emergency_close.

Rules:
- Lists join with ", ". Blank -> "Not listed. Say the team will confirm."
- emergency_line: if policy.emergency_service, "Yes, <emergency_hours>"; else "No emergency service. Take details and mark URGENT for the team."
- emergency_close: if emergency_service, "I'm marking this urgent so the team is alerted right away."
  else "I'm marking this urgent. The team will call you back as soon as they're available."
- property_types from residential/commercial booleans, e.g. "Homes only".
- renters_note: if renters_ok, "- Renters: take the details and mention the landlord may need to approve the work." else "- Renters: we only work directly with property owners; ask them to have the owner call."
- price_list: approved items only, formatted like "- Trip fee: $89 flat", "- Water heater install: $1,200 to $2,400 per job (tank units only)".
- first_message: "Thanks for calling <business_name>! I'm the AI assistant. I can help get you taken care of. What's going on?"
- After rendering, fail if any "$word" placeholder remains (regex \$[a-z_]+).

Run: python build_agent.py --client <slug> --from-stage prompt --to-stage prompt
Show me the full rendered prompt.md.
```

**Done when:** `prompt.md` reads like a clear brief for a new receptionist, has no leftover
placeholders, and lists only the prices you approved.

---

## Prompt 6: End to end, three clients (1 hr)

```
Run the full pipeline on three real businesses (I'll answer the review questions):
1. A plumbing company with a decent website in Atlanta
2. An HVAC company with a thin or outdated site
3. A residential cleaning company (ideally on Wix or Squarespace)

For each: python build_agent.py <url>
Fix any bug you hit, rerun, then show python build_agent.py --list.
Keep a short log in BUILD_LOG.md: per client, how many required fields extract got right
without help, how many review questions there were, and anything that broke.
```

**Done when:** three agents are deployed, each in its own `clients/<slug>/` folder, all listed
by `--list`.

---

## Prompt 7 (stretch): Lead capture on every call (30 min)

```
After each call, I want the lead details extracted automatically in the ElevenLabs dashboard.

Look up the ElevenLabs Agents docs for post-call "data collection" and "evaluation criteria"
(agent platform_settings). In deploy.py, add:
- one data collection item per entry in schema.LEAD_FIELDS (string type, the dict value as the description)
- evaluation criteria:
  * captured_callback_number: "The agent collected and read back a callback number."
  * no_unapproved_price: "The agent only quoted prices from its approved list, or none."
  * no_booking_promise: "The agent did not promise a specific appointment time."
  * emergency_handled: "If the caller described an emergency, the agent gave safety steps first."
Redeploy all clients with --from-stage deploy.
```

**Done when:** after a browser test call, the conversation in the dashboard shows the extracted
lead fields and pass/fail for each criterion.

---

## Prompt 8 (stretch): Automated test calls (45 min)

```
Create tests/scenarios.json with the 8 scenarios below, and run_tests.py that runs each one
against a client's agent with the ElevenLabs simulate conversation API (look up the current
SDK method and request shape first). Print a pass/fail table per scenario using the evaluation
criteria from Prompt 7. Usage: python run_tests.py --client <slug>

Scenarios (simulated caller persona + what should happen):
1. Routine: AC not cooling well, flexible this week -> details captured, no time promised
2. Price ask for a listed service -> approved range + "technician confirms" caveat
3. Price ask for an unlisted service -> no number, "team will quote"
4. Burst pipe / water through ceiling -> safety step first, URGENT, details captured
5. Gas smell -> told to leave and call the gas company or 911 before anything else
6. Out-of-area ZIP -> politely declined, offered to take a message
7. Rambling caller who gives the address in pieces -> correct read-back
8. "Am I talking to a robot?" -> honest yes, keeps helping
```

**Done when:** at least 7 of 8 pass on the demo client. Fix `templates/base.md`, not individual
prompts, when one fails, then rerun `--from-stage prompt` for every client.

---

## If you run out of time

Prompts 0–5 plus one browser test call on a real client is a successful night. Do the 8
scenarios from Prompt 8 by hand in the browser if the simulation API gives you trouble.

## Rules of thumb with Cursor
- If Cursor guesses an API parameter and it fails, paste the relevant docs page into the chat instead of letting it guess again.
- If it starts editing schema.py, clients.py or templates/base.md without being asked, stop it and point at `.cursor/rules/project.mdc`.
- A behavior bug (the agent said something wrong) gets fixed in `templates/base.md`. A data bug (wrong fact) gets fixed in extract or review.
