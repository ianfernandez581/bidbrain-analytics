# Prompt for populating pacing_intake_template.xlsx from the company tracker

Paste the prompt below into a Claude chat together with TWO files:
1. pacing_intake_template.xlsx (this folder)
2. the company campaign tracker exported from Google Sheets (File > Download > .xlsx)

---

You are helping a media agency populate a campaign intake sheet that feeds their pacing system (The Grid). The system tracks, per campaign per platform: who the client is, where the campaign runs, its flight dates and whole-flight budget, and then monitors live spend against that budget through platform APIs. Accuracy matters more than completeness: a wrong budget or a retyped campaign name silently corrupts pacing, while a marked gap just gets filled later.

I am giving you two files:
1. pacing_intake_template.xlsx - the sheet to populate. The Campaigns tab has the columns; the Instructions tab defines every column and where its data lives in each ad platform's UI. Read both tabs first. Delete the EXAMPLE rows.
2. Our company campaign tracker - the current source of truth for what is running. Its layout: rows are grouped under agency section headers (100% DIGITAL, TRANSMISSION); the client name appears once per block in the left column and applies to all rows beneath it until the next client; each row is one campaign on one channel. Columns include Job Number, Campaign Name, Channel, Objective, Managed By, Status, Start Date, End date, Campaign Margin. Process every data row, including any not visible in a first glance; skip section headers and blank spacer rows.

YOUR TASK
Produce one output row per campaign-per-platform in the EXACT column order of the template's Campaigns tab. Fill every cell you can derive from the tracker. For anything the tracker does not contain, write exactly NEEDED in the cell - never guess, never invent, never leave silently blank. Then produce a collection checklist of every NEEDED cell, grouped by the Managed By person, so each owner gets one list of what to hunt down.

COLUMN MAPPING
- client: the block's client name from the left column (Gateway, VMCH, ResetData, Cloudflare, ...).
- agency: from the section header the row sits under (100% Digital or Transmission).
- platform: from Channel, normalized to exactly one of: Trade Desk, LinkedIn, Google Ads, Meta, DV360, Reddit, DOOH, LINE. (TradeDesk becomes Trade Desk; Linkedin becomes LinkedIn.)
- account_or_advertiser_id, account_name_exact, campaign_id: the tracker does not hold these - NEEDED.
- campaign_name_exact: use the tracker's Campaign Name BUT flag it. Tracker names are often internal shorthand (Always On, Star Card), not the platform's exact spelling, and pacing matches on the platform's spelling. Put the tracker name in the cell followed by a space and (VERIFY EXACT PLATFORM NAME), and list it on the checklist. Grain rules: for LinkedIn rows the name and id must be the CAMPAIGN GROUP, for DV360 rows the INSERTION ORDER.
- flight_start, flight_end: from Start Date / End date, converted to YYYY-MM-DD. Formats like 27-Jul-2026 are unambiguous. If a date cell is empty or held by a note like Flag, write NEEDED.
- budget_total, budget_currency, budget_basis: the tracker holds no budgets, so normally NEEDED. Currency defaults you may prefill (mark them (CONFIRM) in the cell): Cloudflare USD, STT SGD, Schneider AUD, ResetData AUD, Caltex AUD, VMCH AUD, The Little Marionette AUD, Gateway AUD, PropTrack AUD. budget_basis is always CLIENT_BILLED or MEDIA_COST and always NEEDED unless a document states it.
- spend_mult, imp_target, click_target, lead_target: NEEDED unless stated somewhere; leave the targets NEEDED only for rows whose Objective implies them (Leads objective wants lead_target, Awareness wants imp_target, ROAS or Traffic can leave targets blank).
- platform_margin: leave blank. Do NOT copy the tracker's Campaign Margin column into it - they are different concepts. Instead append the tracker margin to notes as tracker margin: X%.
- status: from Status (Active, Paused, Ended, Not launched). Skip rows marked Ended unless I tell you otherwise.
- manager: from Managed By.
- notes: combine anything informative: Job Number (job 2479), the Objective, tracker margin, any Flag or oddity you noticed on that row (for example a #DIV/0! cell or a Flag marker in a date column).

OUTPUT
1. The populated table, as a downloadable file matching the template's Campaigns tab headers exactly (CSV is fine).
2. The collection checklist, grouped by owner (Managed By), each item naming the client, campaign, and the exact columns still NEEDED, with a one-line pointer on where to find each (the template's Instructions tab tells you where each id lives in each platform's UI - reuse that).
3. A short list of anything in the tracker that looked wrong or ambiguous (duplicate rows, missing dates, rows you were unsure how to group). Do not silently fix these - surface them.

RULES
- Never invent a value. NEEDED is a good answer; a guessed budget is a corrupt one.
- Copy names verbatim, character for character. Do not tidy capitalization or spacing.
- One tracker row = one output row. If a tracker row clearly spans two platforms, split it and note it.
- Use plain dates (YYYY-MM-DD) and plain numbers (no currency symbols, no thousands separators).
