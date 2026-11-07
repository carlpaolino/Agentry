# Build log

Prompt 6: full pipeline on three real businesses, 2026-10-31.
"Required right without help" = of the 6 REQUIRED_PROFILE_FIELDS, how many extract got right,
spot-checked against the saved pages.

## 1. Plumbing Express (plumbing, decent site)
- URL: https://plumbingexpress.com/ (slug `plumbingexpress`)
- Crawl: 168 candidates, 10 pages saved.
- Required right without help: 6/6 found. main_phone (770) 258-6701 is the /contact number,
  but nearly every page shows a different number (call tracking), so the operator should confirm it.
- Draft prices: 0 (site publishes none).
- Staleness flagged: 7, including 24/7 claims on the home page vs "no after-hours dispatch" on the
  leak page, and different repipe warranties on different pages.
- Review questions: pending
- Broke: nothing.

## 2. Empire Heating & Air Conditioning (HVAC, thin site)
- URL: https://empirehvac.com/ (slug `empirehvac`)
- Crawl: 200 candidates (cap hit), 10 pages saved.
- Required right without help: 5/6. business_hours missing; confirmed the site states no hours
  anywhere, including the footer.
- Draft prices: 4. Three tune-up promo prices ($118, $168, $399) are real, but no expiry date is shown.
  "AC install $5,000 to $10,000" is a typical-market range from a financing article, not Empire's
  price, so reject it in review.
- Emergency: 24/7 only for Planned Maintenance members; review defaults emergency to yes, so adjust.
- Review questions: pending
- Broke: nothing in this client; see the crawl fixes below.

## 3. Mo's Krystal-clear / Clean Bees (cleaning, Wix free site)
- URL: https://moniquemurphy72.wixsite.com/mysite (slug `moniquemurphy72-wixsite`)
- Crawl: 11 candidates, 8 pages saved (the whole site).
- Required right without help: first run 4/6 (hours missing, name inferred); after the footer fix
  6/6 found. business_name came out as "Clean Bees" (footer copyright) while the home page says
  "Mo's Krystal-clear cleaning services"; the operator must pick one.
- Draft prices: 0. Correct: the only amount is a $25 same-day cancellation fee.
- Staleness flagged: copyright 2023; conflicting late-cancellation fees.
- Review questions: pending
- Broke: two crawl bugs, both fixed (below).

## Bugs found and fixed
1. **Footer content dropped** (crawl.py). Firecrawl's scrape defaults to main content only,
   which strips footers. Mo's hours ("operating Hours between 8am -8pm") live only in the footer, so
   extract reported hours missing. Fix: `only_main_content=False`. Checked: the same scrape went from
   no hours line to the hours line.
2. **Rate limit silently lost pages** (crawl.py). Firecrawl's plan allows about 10 requests a minute;
   the re-crawl lost /about-us and /faq ("Rate Limit Exceeded") and still wrote pages.json. Fix: on a
   rate-limit error, wait 30s and retry (up to 2 times). Rerun: one wait, 8/8 pages saved.

Old page sets were moved, not deleted, to `clients/moniquemurphy72-wixsite/source/pages.before-footer-fix/`
and `pages.rate-limited/` (extract only reads `source/pages/`).

## Known, not fixed
- Plumbing Express and Empire were crawled before the footer fix. Both got all footer-type facts
  that exist, so they weren't re-crawled.
- centralheatofga (Prompt 2 client) was also crawled before the footer fix; its hours are not in
  the footer either (checked), so nothing is lost.
- `build_agent.py` sets status to the last stage run, even when that stage skipped, so re-running an
  early stage moves the status backwards.
