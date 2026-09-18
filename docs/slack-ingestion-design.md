# ADR: Slack channels into the knowledge base

> Status: **PROPOSED - built locally, not connected, not deployed** (2026-09-17) · Author: Jerome
> (drafted with Claude) · Date: 2026-09-17
> Scope: `bidbrain-platform` (`kb_slack.py`, `kb_slack_routes.py`, `/kb/channels`). A sibling of the
> Fathom connector described in [rag-assistant-design.md](rag-assistant-design.md) §7 and the
> platform README -> "Meetings". Task tracking: `C:\Projects\BidbrainAI\Slack_Ingestion_Task_Breakdown.xlsx`.

## 0. The one open gate

Slack's [App Developer Policy](https://docs.slack.dev/developer-policy) (effective 2024-12-10, read
2026-09-16) binds every developer using the APIs, internal apps included, and prohibits:

- "Using Data to train an LLM under any circumstances"
- "Renting, selling or sharing Data with third parties under any circumstances"
- collecting or storing Data "without obtaining proper consent"
- keeping Data more than 14 business days after the app is uninstalled

Neither "third parties" nor "train" is defined. This library sends retrieved text to Gemini,
Claude and Kimi over their APIs, and the meetings ladder sends conversation text to
`gemini-2.5-flash` to decide which client it belongs to. The engineering reading is that an API
sub-processor whose current terms say *no training on inputs, bounded retention* is a processor,
not a third party, and that embeddings + `kb_memory` routing facts + `kb_feedback` trust nudges are
retrieval ranking, not model training. **That is a legal reading, not an engineering one. Nobody
connects a real workspace until Jerome and Ian have taken it** (Decision D-01 in the workbook).
Everything below is built so that nothing is stored until a token is mounted.

## 1. Decision in one paragraph

Slack channel conversations become ordinary knowledge-base documents, filed to a client the same way
Fathom meetings are, through the same ladder, with the same queue and the same audit record. The
scope control is the Slack invite: the bot reads only channels a person has added it to, and nothing
about a channel's *name* is a rule in code. A channel a person has mapped to a client on the page
files without a model call; an unmapped one is judged conversation by conversation by AI + RAG +
memory, exactly like a meeting (Jerome, 2026-09-16: decisions come from AI, RAG and memory, not
codified rules). The alternative Slack itself recommends for AI - the Real-time Search API
(`assistant.search.context`) - was considered and set aside for v1 because it forbids storing
anything, so it can never feed the vector store or memory, which is the stated goal.

## 2. What a conversation is

| Slack shape | Document | id | title |
|---|---|---|---|
| a thread (parent + replies) | one document | `slack-<channel>-t<parent ts>` | first line of the parent `(#channel, date)` |
| unthreaded messages of one day | one document | `slack-<channel>-d<YYYY-MM-DD>` | `#channel - date` |

`kind=conversation`, `source=slack` (both added to `kb_store` on 2026-09-17 - Ian's schema, to be
told), folder `Slack/#<channel>` under the client, body one `[HH:MM] Name: text` line per message
with mentions resolved to names, channel refs to `#name`, links to `label (url)`, files as
`[file: name]` only (never downloaded). Days are bucketed in `SLACK_TZ`, read at call time so the
zone is a config change rather than a redeploy (default `Asia/Manila` - the day boundary belongs
where the people TYPING sit, not where the clients do; the `tzdata` pin exists so a slim image
cannot silently fall back to UTC). The
raw messages ride as the document's file (`conversation.json`); Slack facts (channel, thread,
permalink, who assigned it and why) ride on the doc object under `slack`, invisible to the index.
Why not one document per message: `kb_index` chunks at ~220 words and a Slack message averages a
dozen; a thread is one conversation and a day of loose chatter is the next best unit.

## 3. Events are triggers, history is the truth

A Slack event (`message`, `message_changed`, `message_deleted`) is never used as text. It says "this
channel changed"; the connector re-reads that channel from `conversations.history` /
`conversations.replies` around the event's timestamp and rebuilds the affected documents under the
same ids and the same client. Consequences that fall out for free:

- an edit reads as edited; a deleted message is simply absent after the rebuild (the Policy's
  "honour deletion", with no per-subtype code);
- `POST /slack/events` and `Sync now` share one code path (`_sync_quietly` / `sync_channel`);
- the raw event is kept in `slack/inbox/<event_id>.json` for idempotency and the audit trail only.

`conversations.history` filters by the PARENT's timestamp, so a reply posted today to last week's
thread is invisible to "everything since the watermark". Each sync therefore re-reads a 14-day
lookback (`SLACK_LOOKBACK_S`) and relies on `kb_index.reindex_document` being idempotent, so an
unchanged conversation costs nothing and writes nothing to the audit record.

## 4. Filing

```
already filed?  -> rebuild under the same client (an edit/delete upstream), no audit line
channel mapped? -> file, assigned_by=channel, slack_filed          (a person declared it; no model)
else            -> kb_fathom.classify(as_meeting(conv))            (memory -> evidence -> one synthesis)
                   >= FATHOM_AUTO_ASSIGN and names a client / agency work -> file, slack_filed
                   else -> slack/unassigned, slack_queued, a person decides on /kb/channels
```

`as_meeting` is a meeting-shaped view of the conversation (title, speaker turns, and the people who
SPOKE standing in for the invite list) so the ladder AND memory run unchanged: a recurring external
guest is learned on a human Assign and matched by the memory rung next time; an all-staff channel
has no external author, so rungs 0 and 1 contribute nothing and the transcript decides - the rule
Jerome set for internal meetings applies to chat verbatim. The channel mapping lives in
`slack/channels.json`, declared by a person on the page, audited as `slack_mapped`; changing it
never moves already-filed documents - that is a second, explicit button (`/kb/api/slack/refile`,
audited `slack_moved`), the K7-10 safe-Assign rule.

## 5. What never happens

- No direct messages: the manifest carries no `im:*` / `mpim:*` scope.
- No posting: no `chat:write`.
- No private channels in v1: no `groups:*` scope, `list_channels` falls back to public-only when
  Slack answers `missing_scope`, and even with the scope a private channel is listed but NOT read
  until `SLACK_ALLOW_PRIVATE=1` (`kb_slack.readable`). That switch is where the membership filter
  (workbook S5-01) has to exist.
- No customer ever sees a Slack document: `kb_bridge.retrieve_for_client` drops `source=slack` and
  `kind=conversation` whatever their `visibility` says (test in `test_kb_slack_routes.py`).
- No distribution: the app is internal to the 100% Digital workspace. Distributing beyond the org
  drops `conversations.history` to 1 request/min + 15 objects and makes this "Commercial
  Distribution" under the API terms.
- Nothing is stored before `SLACK_BOT_TOKEN` is mounted; nothing is received before
  `SLACK_SIGNING_SECRET` is.

## 6. Lifecycle

| Slack says | We do | Audit |
|---|---|---|
| `app_uninstalled` / `tokens_revoked` | `kb_slack.purge_all()` - every document, chunk, file, queue entry, inbox object, mapping and state | `slack_purged` |
| `channel_rename` | rename in state + mapping; watermark and documents untouched (ids follow the channel id) | `slack_channel` |
| `channel_archive` / `channel_deleted` / bot removed | mark the channel `gone` in state; documents stay - a channel closing does not un-say what was said | `slack_channel` |
| `member_left_channel` by anyone else | nothing | - |

`GET /kb/api/slack/purge-check` reports documents + objects remaining and the last purge time
(`clean: true` when both are zero). Wiring it to a Cloud Scheduler assertion 14 business days after a
purge is a GCP action for Jerome (workbook S5-02, second half).

## 7. Audit and observability

Eight `slack_*` kinds in `kb_activity.KINDS`, grouped as `slack` so the type filter on
`/kb/channels` and the Observability page never mixes them with meetings, searches or document
edits (Jerome, 2026-09-17: "it might get confusing because it can get mixed to the audit of other
process"). One event per DECISION: filed / queued / assigned / ignored / moved / mapped / purged /
channel. A rebuild is not a decision and writes nothing. Observability shows a Slack panel the
same shape as Meetings, plus "by a mapped channel" - the filings that needed no judgement, which
is the number that should grow.

## 8. Facts this rests on (read 2026-09-16 unless stated)

- Auth is an installed OAuth app; a bot token `xoxb-` comes from the install. No API key exists.
- Internal apps: `conversations.history` / `replies` Tier 3, ~50+ req/min, 999 per page.
- Events API: reply within 3 s, up to 3 retries (`X-Slack-Retry-Num`), ~30,000 events/hour.
- Signing: `X-Slack-Signature = v0=HMAC-SHA256(secret, "v0:<ts>:<raw body>")`, ~5-min tolerance.
- Free plan: history visibility 90 days; the API sets `is_limited` when it withholds older messages.
  **Not yet tested against a real workspace** (workbook S0-07) - the connector records the flag.
- `app_uninstalled` and `tokens_revoked` arrive in no guaranteed order; either starts the purge.
- Real-time Search API: search on behalf of the USER, permission-perfect, "you must not store or
  copy any of the data", semantic search only on Business+/Enterprise+. Option B if §0 says stop.

## 8a. Provider terms, checked 2026-09-17 (S0-03 / Decision D-05)

What each provider's CURRENT published terms say about text sent through its API. Read on
2026-09-17; re-verify before citing (ADR-0051's rule: never from memory).

| Provider | Endpoint we call | Training on API inputs | Retention | Source |
|---|---|---|---|---|
| Google Gemini API, **paid** tier | `generativelanguage.googleapis.com` (the meetings/Slack ladder's classifier; the Ask panel when Gemini is chosen) | "Google doesn't use your prompts ... or responses to improve our products" | "logs prompts and responses for a limited period of time, solely for detecting and preventing violations of the Prohibited Use Policy" | [Gemini API terms](https://ai.google.dev/gemini-api/terms), last updated 2026-04-28 |
| Google Gemini API, **unpaid** tier | same endpoint, a key from a project WITHOUT billing | Google uses content "to provide, improve, and develop Google products and services and machine learning technologies"; "human reviewers may read, annotate, and process your API input and output" | not bounded | same page |
| Google Vertex AI | `aiplatform.googleapis.com` (`text-embedding-005`, the library's vectors) | "By default, Google Cloud doesn't use customer data to train its foundation models" | prompts cached up to 24 h by default (can be turned off per project); abuse logging only for non-invoiced accounts | [Vertex data governance](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/data-governance) |
| Anthropic API | `api.anthropic.com` (the Ask panel when Claude is chosen) | "Anthropic may not train models on Customer Content from Services" | inputs and outputs deleted "within 30 days"; zero-data-retention agreements exist | [Commercial Terms](https://www.anthropic.com/legal/commercial-terms) eff. 2025-06-17; [retention](https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-personal-data) |
| Moonshot / Kimi API | `api.kimi.com/coding/v1` (the Ask panel's DEFAULT provider) | Moonshot "may use Content to ... improve Moonshot AI models"; "Unless otherwise expressly agreed in writing, Customer Content may be used for the foregoing purposes"; opt-out only via "enterprise arrangements or separate written agreements" | not stated; storage location not stated | [Kimi OpenPlatform terms](https://platform.kimi.ai/docs/agreement/modeluse), last updated 2026-07-30 |

Two consequences:

1. **Kimi trains on what it is sent by default.** BUILT (S5-04, 2026-09-17 evening, Jerome: "continue
   with the code"): Slack-derived passages are withheld from Kimi in code - `kb_slack.withhold_from`
   decides from what was RETRIEVED, `kb_routes.ask` passes it as `kb_chat.stream(exclude=...)`, the
   person's chosen model is overridden for that one answer only, and the model badge says
   "Gemini · not Kimi" with the reason on hover. `KB_SLACK_EXCLUDE_PROVIDERS` (default `kimi`) so a
   signed no-training agreement is a config change. Meeting transcripts are NOT withheld - that is
   decision A in the report, still Jerome's and Ian's. It is not a judgement about Kimi's quality; it is the one term that
   fails the Policy test. Meeting transcripts are arguably in the same position and are NOT yet
   withheld - a decision for Jerome and Ian, not something to change quietly.
2. **The Gemini API key's tier is UNKNOWN.** `bidbrain-analytics` is billed, but it has no API
   keys of its own and `generativelanguage.googleapis.com` is not enabled on it, so the
   `gemini-api-key` secret was created in some OTHER project (an AI Studio key). If that project is
   unbilled, the classifier has been running on the UNPAID tier, where Google may use prompts to
   improve products and humans may read them - for meeting transcripts today, Slack tomorrow.
   Resolution is one of: confirm the key's project is billed; or enable the Gemini API on
   `bidbrain-analytics` and mint a key there; or move the classifier to Vertex (`aiplatform` is
   already enabled and does not train by default). Jerome's call; nothing in code assumes either.

## 9. Sequencing (what is left)

1. Jerome + Ian: the legal read (§0) and the provider-terms table (Gemini API paid tier, Anthropic
   API, Kimi/Moonshot: training, retention, region - verified against current vendor terms, per
   ADR-0051's rule).
2. Jerome: create the app from `slack-app-manifest.yaml`, install, mount the two secrets, invite the
   bot to Geocon's channel, map it to Geocon on the page.
3. The 90-day test and volume sizing on the first real sync (S0-07, S4-06).
4. Charles: the consent notice and team announcement BEFORE the first backfill (S0-08 / D-09).
5. Then, in order: events URL registered in Slack after the deploy (the manifest omits it because it
   verifies at save time), provider guard in code (S5-04), memory learning from confirmed
   conversations (S6-02), private channels + membership filter (S5-01) only if asked.
