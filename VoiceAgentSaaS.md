# Voice Agent SaaS: From Agency to Self-Serve Product

Oct 21, 2026 · @Raghavan

## The core idea

The pledge has proven demand, not a product: home-service owners will pay $1,000–$5,000/month to stop missing calls. Scaling means replacing his hand-building with software that does the same build from a 5-minute conversation.

What he does by hand today, and what the product must automate:

| His manual step | Product equivalent |
| --- | --- |
| Interviews the owner about services, prices, hours, service area | Onboarding chat that asks the same questions, or scrapes their website and Google Business profile to pre-fill |
| Writes the Voiceflow flow and prompt | System generates the agent config from a vertical template + the owner's answers |
| Picks an ElevenLabs voice | 4–6 preset voices with a play button |
| Wires up the calendar | One-click Google/Outlook OAuth, later Jobber / Housecall Pro / ServiceTitan |
| Sets up the phone number | Provision a new number instantly, then show carrier-specific call-forwarding steps |
| Tests it and tweaks after complaints | "Call your agent now" test button + a transcript inbox where the owner fixes a wrong answer in plain English |

The key insight: the owner should never see a flow builder. Voiceflow is for builders; your customer is a plumber in a truck. Everything is a form, a chat, or a toggle.

## Market reality

Self-serve AI receptionists already exist, so "easy signup + calendar + phone number" alone is not a moat. The opening is in what incumbents do badly: vertical depth, job-software integration, and owner trust.

| Player | What they do | Gap you can exploit |
| --- | --- | --- |
| [My AI Front Desk](https://www.myaifrontdesk.com/other-industries/hvac-service) | Horizontal self-serve: paste details, pick a voice, forward your number, live in under an hour | Generic across every industry; shallow on trade-specific triage and dispatch |
| [Sameday AI](https://solvea.cx/blog/best-ai-receptionist-for-hvac) | Built for home services (HVAC, plumbing, roofing) | Demo-only, no self-serve signup |
| [Avoca AI](https://solvea.cx/blog/best-ai-receptionist-for-hvac) | Multi-location HVAC enterprises | Custom pricing, hands-on implementation; ignores small shops |
| [Smith.ai](https://solvea.cx/blog/best-ai-receptionist-for-hvac) | AI + live human agents | Expensive, human-labor cost structure |
| Retell, Vapi, Synthflow, Bland | Developer platforms for building voice agents | Not for owners; these are your infrastructure, not your competition |

Where a new entrant can win:

- **Self-serve AND vertical-deep.** Sameday and Avoca have the HVAC depth but force a sales demo; My AI Front Desk has self-serve but is generic. Nobody obviously owns both for small trade shops.
- **Books into the dispatch board, not just a calendar.** [ServiceTitan, Housecall Pro, and Jobber all have APIs](https://www.open.cx/blog/ai-for-hvac-business-2026) that let an AI book against the right tech, zone, and service code. A Google Calendar slot is a toy for a 6-truck HVAC shop.
- **Emergency triage done right.** The biggest risk in HVAC voice AI is the agent improvising an emergency response. Hard-coded escalation rules (no-heat with elderly occupant → page the on-call tech) are a trust feature you can sell.

Pick ONE vertical to start (HVAC is the obvious one given the pledge's customers) and be visibly the best tool for it.

## Product: signup to live phone line in 5 minutes

The goal is that an owner hears their own agent answer a test call before they've typed a credit card. Every screen is one decision, and the system guesses everything it can.

1. **Enter your website or business name.** The system pulls the Google Business profile and website: services, hours, service area, phone, reviews. The owner confirms instead of typing.
2. **"What should your receptionist do?"** Three big checkboxes, not a prompt box: Book appointments · Answer questions & take messages · Handle emergencies. A free-text box sits below for anything else ("never quote prices over the phone").
3. **Fill the gaps in a chat.** The onboarding AI asks only what it couldn't scrape, in trade language: "Do you charge a diagnostic fee? How much?" "What counts as an emergency for you?" "Who gets called for after-hours emergencies?"
4. **Pick a voice.** Five or six preset voices with play buttons, plus the agent's name.
5. **Connect your calendar.** One OAuth click for Google or Outlook. Jobber / Housecall Pro / ServiceTitan show as options once built. Skippable: the agent can take messages and text the owner instead.
6. **Test call.** "Call this number now and pretend you're a customer." This is the conversion moment; the owner hears it work before paying.
7. **Go live.** Option A: get a new local number instantly. Option B: keep their number and forward to the agent, with step-by-step instructions auto-detected for their carrier (Verizon, AT&T, RingCentral, etc.) and a "forward only when I don't answer" default.
8. **Pay.** Card entry after they've heard it work. Trial minutes included.

After launch, the product is a phone-first dashboard:

- **Call inbox:** every call with summary, transcript, recording, and outcome (booked, message, emergency escalated, spam).
- **"Fix this answer":** tap a wrong reply in a transcript, type the correct answer in plain English; it updates the agent's knowledge.
- **Instant texts:** owner gets an SMS for every booking and every emergency, so they trust it without opening the app.
- **Weekly email:** "Your agent answered 47 calls, booked 12 jobs, caught 9 after-hours calls." This is the retention engine, because it shows ROI in dollars.

What to deliberately leave out of v1: flow builders, prompt editing, model selection, analytics dashboards, multi-agent setups. Each one is a reason for a non-technical owner to bounce.

## Architecture and tech stack

Don't build voice infrastructure; rent it and build the layer that turns an owner's answers into a working agent. Move off Voiceflow: it's a visual builder for humans, while you need an API you can configure programmatically.

&#91;embedded content: system architecture · 6 components\]

The owner only touches the web app. Your backend writes the agent config to the voice platform and receives call events back; during a call, the agent calls your backend's tools to check availability, book, or escalate.

| Layer | Recommended choice | Why |
| --- | --- | --- |
| Voice runtime | Retell AI or Vapi | API-first, so each signup creates an agent automatically; Retell includes [20 concurrent calls](https://www.getmacha.com/blog/retell-ai-vs-vapi), Vapi is cheaper if you bring your own model keys |
| Voices | ElevenLabs, via the voice platform | Keeps what the pledge already uses |
| Onboarding + config generation | Claude API | Turns scraped site + chat answers into a structured agent spec and system prompt |
| Web app | Next.js + Supabase (auth + Postgres) | Fast to ship, one person can run it |
| Phone numbers + SMS | Twilio (often bundled by the voice platform) | Number provisioning, forwarding, text alerts |
| Calendar | Google Calendar + Microsoft Graph APIs; Cal.com as a shortcut | One-click OAuth |
| Job software | Jobber and Housecall Pro first, ServiceTitan later | ServiceTitan's partner process is slower; start where small shops are |
| Billing | Stripe | Subscriptions + usage overage |

The core asset you own is the **agent spec**: a structured JSON document per business (services, prices, hours, service area, triage rules, escalation contacts, booking rules). The prompt is generated from it. That keeps every agent editable through simple forms and lets you swap voice platforms later.

## Pricing and unit economics

Self-serve can't charge $1,000–$5,000/month; that price is paying for the pledge's time. A self-serve tier around $200–$500/month still has 70%+ gross margin, and the done-for-you service stays as the premium tier.

Cost per minute: all-in voice agent costs run roughly [$0.07–$0.30 per minute](https://techsy.io/en/blog/ai-voice-agent-pricing) once telephony, speech-to-text, the LLM, and TTS are included. Plan on about $0.15/min.

A typical small HVAC shop: \~300 calls/month × 3 min = 900 min ≈ $135/month in voice cost, plus \~$1–$2/month per phone number.

| Tier | Price/month | Included | Est. cost at full use | Target customer |
| --- | --- | --- | --- | --- |
| Starter | $199 | 500 min, messages + calendar booking | \~$75 | Solo operators, 1–2 trucks |
| Pro | $449 | 1,500 min, emergency routing, job-software integration, SMS follow-up | \~$225 | 3–10 truck shops |
| Done-for-you | $1,500+ | Pro + custom build, monthly tuning, outbound campaigns | \~$300 + labor | Shops that want a human (the pledge's current model) |

Pricing notes:

- **Flat tiers, not per-minute.** HVAC call volume spikes in summer and winter; owners hate bills that jump. Competitors already sell against metered pricing, so match them.
- **Overage at \~$0.30/min**, with a text warning at 80% usage.
- **Free trial = 50 minutes, no card until the test call works.**
- **Sell on ROI, not features.** If one missed HVAC call is a $300–$8,000 job, booking two extra jobs a month pays for Pro.

## Go-to-market: the agency is the wedge

Don't kill the agency; it is your cash flow, your customer research, and your template library. Every client the pledge hand-builds becomes a template and a case study for the self-serve product.

- **Turn his builds into templates.** Each Voiceflow agent he ships is a spec: the questions customers ask, the triage rules, the booking logic. Ten HVAC builds = one excellent HVAC template.
- **Migrate existing clients first.** Move his paying clients onto your platform at their current price. They are your first production users, and their call logs show where the agent fails.
- **Keep his outbound, change the offer.** His cold calls and emails currently sell a $2,000 build. Instead, send the prospect a link: "I built your receptionist already, call this number." Pre-build a demo agent from their website before the call. That converts far better than a pitch.
- **Go where owners already are.** Trade Facebook groups, HVAC subreddits, supply houses, and partnerships with field-service software resellers and local trade associations.
- **Use the agent as the marketing.** "Powered by \[YourName\]" option in the call wrap-up text, and a referral credit: one free month per referred shop.
- **Collect proof.** Recorded calls (with consent) where the agent books a $4,000 job at 11pm are the best ad you'll ever have.

## Phased roadmap

Ship self-serve in about 12 weeks by productizing what already works, and don't open signups to strangers until the pledge's existing clients are running on your platform without him touching them.

&#91;embedded content: roadmap · 4 phases, 3 gates\]

Each gate is a go/no-go: if migrated clients churn or keep needing hand-tuning in phase 2, fix the agent quality before spending anything on self-serve acquisition. The diamonds mark the criteria to hit before moving to the next phase.

## Risks and open questions

The biggest risk is not technical; it is that self-serve customers churn faster than agency clients because nobody is there to hold their hand.

| Risk | Why it matters | Mitigation |
| --- | --- | --- |
| Self-serve churn | Agency clients stay because a person tunes the agent; DIY users quit after one bad call | Weekly ROI email, "fix this answer" flow, proactive alerts when the agent fails a call |
| Agent mishandles an emergency | A botched gas-leak or no-heat call is a liability and a lost customer | Hard-coded escalation rules outside the LLM; agent never gives safety advice, only routes |
| Crowded market | Well-funded players already sell self-serve receptionists | Win one vertical deeply; integrations and triage quality are the moat, not the voice |
| Platform dependency | Building on Retell/Vapi means their price changes hit your margin | Keep agent config in your own format; abstract the voice layer so you can switch |
| Calling-law compliance | Outbound AI calls fall under TCPA rules; call recording consent varies by state | Start inbound-only; get a lawyer's read before launching outbound features |
| Founder bandwidth | Both of you are full-time students; you already run RealBench | Decide upfront who owns product vs. sales, and set a go/no-go metric at week 8 |

Open questions to answer before building:

- [ ] How many of the pledge's clients would switch to a $449 self-serve plan vs. stay at their current price?
- [ ] What share of his build time is repeatable (template) vs. truly custom per client?
- [ ] Which job software do his HVAC clients actually use? That decides integration #1.
- [ ] Equity and roles: is this his company with you as technical cofounder, or a new entity?
