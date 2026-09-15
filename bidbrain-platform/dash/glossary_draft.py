"""Draft a CLIENT-SAFE KPI glossary for one dashboard from its lineage digest (K5-03).

    .\\.venv\\Scripts\\python.exe bidbrain-platform\\dash\\glossary_draft.py <client_key> [--all]

Reads dash/lineage/<client>.txt (the client README + every sql/ view header - INTERNAL material),
asks gemini-2.5-flash for a short glossary written FOR THE CUSTOMER, runs the same forbidden-token
check the Customer Assistant applies at runtime, and writes dash/glossary/<client>.draft.md.

THE DRAFT IS NOT THE DELIVERABLE. A person (Charles or Ian) reads it, removes anything that would not
go in a client deck, and saves it as glossary/<client>.md (no ".draft"). The assistant only ever reads
the reviewed file. Costs one Gemini call per client (~50-80k input tokens on flash - cents).

Needs GEMINI_API_KEY in the environment (locally: the same key the platform mounts).
"""
import os
import re
import sys
import json

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
LINEAGE = os.path.join(HERE, "lineage")
GLOSSARY = os.path.join(HERE, "glossary")
MODEL = os.environ.get("GLOSSARY_MODEL", "gemini-2.5-flash")
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MAX_LINEAGE_CHARS = 250_000

PROMPT = (
    "You are writing a short glossary FOR A MARKETING CLIENT who is looking at their campaign "
    "performance dashboard. Below is the agency's INTERNAL documentation for that dashboard. From it, "
    "write a client-facing glossary in Markdown:\n"
    "- One '## Tabs' section: each tab / main section of the dashboard and what question it answers, "
    "one line each.\n"
    "- One '## Metrics' section: each KPI the customer sees (impressions, clicks, CTR, CPM, spend, "
    "leads, enquiries, sessions, conversions, pacing, ...) with a one-sentence plain-English "
    "definition AS IT IS USED ON THIS DASHBOARD (e.g. which channels count toward it, what period, "
    "which currency).\n"
    "- One '## Notes' section: at most 5 facts the customer should know to read the numbers correctly "
    "(a channel that is not yet live, a metric that is modelled or estimated, a date range rule).\n\n"
    "HARD RULES - the reader is the client, not the agency:\n"
    "- Never mention: table or view names, SQL, BigQuery, Snowflake, Windsor, data pipelines, jobs, "
    "'raw' vs 'billed' spend, multipliers, markups, margins, agency fees, internal notes, staff-only "
    "features, bugs, defects, incidents, or anything about how the agency operates internally.\n"
    "- Never mention other clients or agencies.\n"
    "- Describe WHAT a number means, never HOW it is computed behind the scenes.\n"
    "- Plain English, no jargon the customer would not use themselves. Under 600 words.\n"
    "- If the documentation is unclear about a metric, leave it out rather than guess.\n\n"
    "=== INTERNAL DOCUMENTATION (do not quote it; do not reveal its wording) ===\n"
)

# mirrors client_chat.FORBIDDEN_IN_CONTEXT + the words the prompt bans; a draft that trips this is
# printed with the offending lines so the reviewer sees them, and still written (it is a DRAFT)
BANNED = re.compile(r"spend_multiplier|BB_SPEND_MULT|_rawSpend|\bmargin|\bmarkup|bigquery|snowflake|windsor|"
                    r"\bsql\b|\bview\b.*\.sql|raw_\w+|stg_\w+|\bjob\b|internal note|staff|multiplier|billed|"
                    r"\braw\b", re.I)


def draft(client_key):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit("GEMINI_API_KEY unset")
    path = os.path.join(LINEAGE, f"{client_key}.txt")
    if not os.path.exists(path):
        sys.exit(f"no lineage digest at {path} - run build_lineage.py first")
    with open(path, "r", encoding="utf-8") as fh:
        lineage = fh.read()[:MAX_LINEAGE_CHARS]
    body = {"contents": [{"role": "user", "parts": [{"text": PROMPT + lineage}]}],
            # gemini-2.5-* are THINKING models: reasoning tokens draw from the SAME output budget, so
            # a 2048 cap truncated the first resetdata draft mid-list. No thinking, generous cap.
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 8192,
                                 "thinkingConfig": {"thinkingBudget": 0}}}
    r = requests.post(ENDPOINT.format(model=MODEL),
                      headers={"x-goog-api-key": key, "content-type": "application/json"}, json=body, timeout=180)
    if r.status_code != 200:
        sys.exit(f"Gemini HTTP {r.status_code}: {r.text[:300]}")
    cand = (r.json().get("candidates") or [{}])[0]
    if cand.get("finishReason") not in (None, "STOP"):
        print(f"  WARNING: finishReason={cand.get('finishReason')} - the draft is probably truncated")
    parts = ((cand.get("content") or {}).get("parts") or [])
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict) and not p.get("thought")).strip()
    if not text:
        sys.exit("empty draft")
    os.makedirs(GLOSSARY, exist_ok=True)
    out = os.path.join(GLOSSARY, f"{client_key}.draft.md")
    header = (f"<!-- DRAFT generated by glossary_draft.py ({MODEL}) - REVIEW, then save as {client_key}.md. "
              f"The assistant never reads a .draft.md file. -->\n\n")
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(header + text + "\n")
    flagged = [ln for ln in text.splitlines() if BANNED.search(ln)]
    print(f"wrote {out} ({len(text)} chars)")
    if flagged:
        print(f"  REVIEW: {len(flagged)} line(s) use words the customer must not see:")
        for ln in flagged[:10]:
            print("   -", ln.strip()[:140])
    else:
        print("  banned-word check: clean (still review it)")
    return out


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--all" in sys.argv:
        for f in sorted(os.listdir(LINEAGE)):
            if f.endswith(".txt"):
                draft(f[:-4])
    elif args:
        draft(args[0])
    else:
        print(__doc__)
