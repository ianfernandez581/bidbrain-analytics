# Client-safe KPI glossaries (Customer Assistant, design §8 / K5-03)

One `<client_key>.md` per dashboard that has `client_chat` on. The Customer Assistant reads it as
its GLOSSARY block - plain descriptions of what each KPI, tab and chart on that dashboard means,
written for the CUSTOMER.

Rules for a glossary file:

- Written for the client. No table names, no view names, no raw-vs-billed talk, no internal
  gotchas, no agency commentary. If a sentence would not go in a client deck, it does not go here.
- Derive it from the client README + `dash/lineage/<client>.txt`, then a person (Charles or Ian)
  reads it once before it is committed. `build_lineage.py --client-glossary <client>` drafts one
  (K5-03); the draft is not the deliverable, the reviewed file is.
- Keep it short (a few KB). It rides in every customer turn.
- No file => the assistant says "(no glossary for this dashboard yet)" and answers from DATA alone.

`client_chat.FORBIDDEN_IN_CONTEXT` refuses a turn whose assembled context contains
`spend_multipliers`, `BB_SPEND_MULT`, `_rawSpend` or the word `margin` - a glossary that trips it
is a glossary that needs rewriting.
