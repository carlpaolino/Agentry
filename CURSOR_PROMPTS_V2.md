# Cursor Prompts v2: notes in, agents out

**Goal:** the pledge runs his cold calls exactly as he does today, then drops what he learned into the
dashboard, and it builds that business's agents for him. That takes him from 3–4 hand-built clients a
month to as many as he can sell.

**v1 deliverable per client** (matches his offer):
- Voiceflow chat agent for the website (main product) + embed snippet
- Optional ElevenLabs phone agent from the same intake
- Lead capture with preferred time (booking comes in v2), escalation to a human, after-hours coverage
- Baseline numbers saved for the monthly report

Paste these into Cursor Agent mode one at a time. Don't move on until "Done when" passes. Commit after each.

---

## Where the code stands (Nov 7)

| Piece | State |
| --- | --- |
| crawl, extract, review, prompt, deploy (ElevenLabs) | Working (CLI) |
| `demo.py`, `--demo` flag, `app.py` Streamlit dashboard (demo + onboarding) | Working, tested offline |
| `schema.Intake` + `monthly_revenue_at_risk` | Written |
| `intake.py`: website + pasted notes -> intake.json, policy.json, prices to approve | Written, **not yet run against Claude** |
| `templates/base.md` v2: chat or phone, FAQs, brand voice, escalation, booking notes, won't-quote | Written; `prompt_builder.render(..., channel="chat"/"phone")` works |
| Roofing and lawn care trades + emergency rules | Written |
| Voiceflow builder | **Not started** |
| Dashboard using intake + Voiceflow | **Not started** |
| Owner lead alerts | **Not started** (v1.1) |

Nothing since the Oct 31 commits is committed.

---

## Prompt 0: Check and commit (10 min)

```
Read .cursor/rules/project.mdc, schema.py, intake.py, prompt_builder.py, demo.py, app.py.
Then:
1. Run: python build_agent.py --client demo-plumbing --from-stage prompt --to-stage prompt
   and show me the first 40 lines of clients/demo-plumbing/agent/prompt.md.
2. Run: streamlit run app.py and confirm it starts (just the terminal output).
3. Update .cursor/rules/project.mdc: add intake.py, demo.py, app.py, the Intake model, the two channels
   (chat via Voiceflow, phone via ElevenLabs), and the trades roofing and lawn.
4. Commit everything with message "intake model, chat/phone templates, dashboard v1".
```
**Done when:** the prompt renders, the app starts, and it's committed.

---

## Prompt 1: Test the notes-to-intake step (30 min)

```
Add a --notes <file> option to build_agent.py: after extract, if --notes is given, call
intake.run(cdir, notes_text, {"business_name": "", "employee_count": ""}) instead of review/demo.

Create samples/notes_empire.txt with realistic messy call notes for Empire HVAC: 6-8 missed calls a week,
"about 6 of 10 book", average job $450, owner Mike answers his own cell, uses Jobber, 2-hour arrival
windows, no estimates on full system replacements over the phone, angry customers and commercial
rooftop units go straight to Mike, casual friendly tone, 3 FAQs with answers, a ZIP list.

Run: python build_agent.py --client empirehvac --from-stage extract --to-stage review --notes samples/notes_empire.txt
Show me intake.json and the price items it added. Check nothing was invented that isn't in the notes or website.
```
**Done when:** `intake.json` reflects the notes, the prices come in unapproved, and nothing is made up.

---

## Prompt 2: Voiceflow builder (1.5 hrs)

```
Create voiceflow_deploy.py with run(cdir, prompt, first_message) that creates or updates this client's
Voiceflow web-chat agent. Use httpx (already installed with anthropic). Env: VOICEFLOW_API_KEY
(personal access token, sent as "Authorization: Bearer <token>"), VOICEFLOW_WORKSPACE_ID.
Add both to .env.example.

Endpoints (base https://realtime-api.voiceflow.com). Before coding, open each page's .md version under
https://www.voiceflow.com/docs/api-reference/ and confirm the shape; tell me anything that differs.
1. Create project:   POST /v1/stable/project  {"name": "<Business> - Website Assistant",
                     "workspaceID": ..., "type": "webchat"}  -> project.id
2. Main environment: GET /v1/stable/environment?projectID=...  -> environments[], use the one with isMain (alias "main")
3. Set the prompt:   PATCH /v2/stable/agent?projectID=...&environmentAlias=main  {"prompt": "<instructions>"}
                     Put the opening line in the prompt ("Start every new chat with: ...").
                     The prompt is Markdown: text in {} or backticks is treated as a reference.
                     Fail if the response lists unresolvedReferences or unresolvedMentions.
4. Publish:          POST /v1/stable/environment/main/publish?projectID=...  {"name": "<timestamp>"}
5. Embed snippet:    GET /v1/stable/widget/snippet?projectID=...&environmentAlias=main&version=published -> snippet

Idempotent: save {"project_id": ...} to clients/<slug>/agent/voiceflow.json and save the snippet to
agent/voiceflow_snippet.html. On a rerun, skip step 1 and redo 3-5. Also write agent/chat_preview.html,
a minimal page with the business name and the snippet, so we can open the chat locally for demos.
Errors: print the HTTP status and body, exit non-zero (same style as deploy.py).

Then refactor deploy.py the same way: deploy_text(slug, prompt, first_message) does the ElevenLabs work;
run(cdir) reads agent/prompt.md and calls it. Behavior of the CLI must not change.

Test with my token on demo-plumbing:
  python -c "from dotenv import load_dotenv; load_dotenv('.env'); import prompt_builder, voiceflow_deploy; ..."
render with channel="chat", deploy, open chat_preview.html.
```
**Done when:** a Voiceflow project appears in the workspace, `chat_preview.html` opens a working chat, and a rerun updates it instead of creating a duplicate.

---

## Prompt 3: Dashboard v2 built around intake (1.5 hrs)

```
Rework app.py (keep the structure and helpers; don't add dependencies):

New client page:
- Fields: website, business name, number of employees, and a large "Paste your call notes" box (optional).
- Button "Read website + notes": crawl -> extract -> intake.run, with st.status steps like today. Then open the client.

Client page tabs:
- Overview: ROI card from schema.monthly_revenue_at_risk ("~$X/month in missed jobs":
  missed calls/week x booking rate x avg job x 4.33), gaps, out-of-date warnings, next step.
- 1 Call notes: edit the Intake fields: owner contact, who answers today, scheduling tool,
  baseline numbers, will-not-quote, booking rules, notify, brand voice, escalation rules
  (one per line), extra lead fields, and FAQs as an editable table (question, answer).
  "Save intake" sets reviewed_intake.
- 2 Business facts, 3 Who we serve, 4 Prices: keep as they are.
- 5 Build:
  - Mode: "Demo (website facts only, no prices)" or "Live (reviewed)". Live is disabled until
    intake, facts, who-we-serve and prices are all saved.
  - Channels: [x] Website chat (Voiceflow)  [ ] Phone (ElevenLabs)
  - Demo must NOT overwrite policy.json or pricing.json: render in memory with
    demo.policy_from_profile(profile) and PricingSheet(share_prices=False).
  - Build: prompt_builder.render(..., channel) per channel, then voiceflow_deploy.run / deploy.deploy_text.
  - Show the outputs: chat preview link (local file), embed snippet in st.code with a copy hint,
    phone "Talk to the agent" link, and the instructions in an expander per channel.
  - Keep the 8 test-call checklist.
Registry: record channels built, voiceflow project_id, and mode.

Test with Streamlit's AppTest (streamlit.testing.v1) with Claude, Firecrawl, ElevenLabs and Voiceflow
monkeypatched, on a COPY of clients/, so real client data isn't touched. Then run it for real once.
```
**Done when:** for a new site plus pasted notes, the pledge goes from "Read website + notes" to a published chat agent and a phone agent with no terminal.

---

## Prompt 4 (v1.1): Lead alerts to the owner (needs a live session)

Do this with the pledge's Voiceflow token, watching the results. Attaching tools needs IDs that only a
live project shows.

```
Goal: when the chat agent has collected a lead, the owner gets an email with name, phone, address,
issue, urgency, preferred window and fit.
Plan: a Voiceflow API tool that POSTs to an email API (Resend: one API key, free tier), with the key
stored as a Voiceflow secret, attached to the agent, with a description telling it to call the tool once
the details are confirmed. Read the Voiceflow docs for API tools, tool attachments, inputs and secrets
(the .md pages, and Voiceflow's "voiceflow-wiring" agent skill) before writing anything. Build it by hand
on demo-plumbing first, read it back with the API, then automate the same calls in voiceflow_deploy.py.
For the phone agent, use ElevenLabs post-call data collection (schema.LEAD_FIELDS) as in CURSOR_PROMPTS.md Prompt 7.
```
Texting owners comes later: business SMS in the US needs A2P 10DLC registration, which takes days to weeks.

---

## Prompt 5 (v1.1): Merge in the pledge's best agent

```
Here is the instructions text from <pledge>'s best Voiceflow agent: <paste>.
Compare it with templates/base.md. Propose edits that bring in his tone, flow and anything he covers that
we don't. Keep every safety rule in base.md (approved prices only, no booking promises, emergencies,
AI disclosure, no payment details). Show me a diff before changing the file.
```

---

## Later (v2)
- Real booking into Google Calendar or Jobber (per-client OAuth) instead of preferred-time capture
- Monthly report: Voiceflow transcripts and analytics API + ElevenLabs conversations, against the baseline numbers
- Phone number per client (Twilio) with call forwarding
- Hosted dashboard with login, so the pledge doesn't need the repo
