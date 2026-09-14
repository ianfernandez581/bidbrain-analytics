"""kb_feedback.py - a buyer's correction becomes a document the next answer can find.

THIS IS THE POINT OF THE WHOLE BUILD. A correction that is only recorded is a complaints box. A
correction that is PROMOTED INTO THE LIBRARY is the system learning: the next person to ask the
same question gets the fix, from a colleague, cited by name.

THE LOOP
    an answer  ->  Right / Right, not here / Wrong
               ->  a one line rule, written BY THE PERSON
               ->  kb/feedback/<id>.json   (the record: question, answer, verdict, who, when)
               ->  a document in "Media buyer knowledge", kind=feedback, trust=verified
               ->  retrieval nudges it up, and pushes down the passages it names
               ->  the assistant is told to SAY it followed a correction, and whose

🔴 THE PERSON WRITES THE RULE, NOT THE MODEL. A model-authored title would mean an LLM writing into
the trusted corpus with nobody approving it, which contradicts the rule that the assistant proposes
and a person acts. The correction box prefills the rule from the first line of what they typed, and
their submit IS the approval.

🔴 A CORRECTION IS NEVER WRITTEN INTO THE DOCUMENT IT CORRECTS. The original stands, unchanged and
still findable. Two documents that disagree is the correct state of the world when a plan was
superseded rather than rewritten, and the assistant is told to say which one wins and why.

🔴 SUPERSEDING IS TICKED, NOT INFERRED. Demoting every passage that happened to be retrieved would
punish seven passages for one wrong sentence. The panel lists the citations, pre-ticks the
top-ranked one (the passage an answer most likely leaned on) and lets the person untick. A
correction with nothing ticked still ranks up on trust; it just does not push anything down.

🔴 "RIGHT, NOT HERE" DOES NOT BY ITSELF MAKE A DOCUMENT. It means the answer was right and the
citation was not, which is a retrieval signal, not new knowledge. It only produces a document when
the person also types something the library does not already say.
"""
import logging

import kb_index
import kb_store

log = logging.getLogger(__name__)

FOLDER = "Media buyer knowledge"
VERDICTS = ("right", "elsewhere", "wrong")
MAX_CORRECTION = 4_000
MAX_RULE = 200


def _body(rule, correction, question, answer, cited, superseded):
    """What the promoted document actually says. Written so it reads as a standalone statement of
    the rule first, with the context underneath: a retrieved passage is read on its own, so a
    document that opens with "you asked X" retrieves as a conversation rather than as knowledge."""
    parts = [rule.strip(), ""]
    if correction.strip() and correction.strip() != rule.strip():
        parts += [correction.strip(), ""]
    parts += ["## Where this came from", "",
              "A buyer corrected an answer to this question:", "",
              "> " + (question or "").strip().replace("\n", " ")[:600], ""]
    if superseded:
        parts += ["This corrects " + ("these passages" if len(superseded) > 1 else "this passage")
                  + ":", ""]
        for ref in superseded:
            title = cited.get(ref, {}).get("title") or ref
            folder = cited.get(ref, {}).get("folder") or "no folder"
            parts.append("- %s (in %s), passage %s" % (title, folder, ref.split("#")[-1]))
        parts.append("")
    if (answer or "").strip():
        parts += ["The answer that was corrected began:", "",
                  "> " + (answer or "").strip().replace("\n", " ")[:400], ""]
    return "\n".join(parts).strip() + "\n"


def submit(*, question, answer, verdict, rule, correction, cited, superseded, actor,
           model="", conv_id="", answer_id="", scope=None, semantic=True):
    """Record one piece of feedback, and promote it when it carries new knowledge.

    `cited` is [{passage_id, document_id, title, folder, trust}] as the answer showed them;
    `superseded` is the subset of passage_ids the person ticked as wrong.

    Returns the feedback record, with `doc_id` set when a document was created.
    """
    verdict = verdict if verdict in VERDICTS else "right"
    rule = kb_store.one_line(rule, MAX_RULE)
    correction = (correction or "").strip()[:MAX_CORRECTION]
    cited_by_id = {c.get("passage_id"): c for c in (cited or []) if c.get("passage_id")}
    superseded = [p for p in (superseded or []) if p in cited_by_id]

    rec = {
        "id": kb_store.new_feedback_id(),
        "at": kb_store.now(),
        "actor": actor or "",
        "verdict": verdict,
        "question": (question or "")[:2000],
        "answer": (answer or "")[:8000],
        "rule": rule,
        "correction": correction,
        "passages": sorted(cited_by_id),
        "superseded": superseded,
        "model": model, "conv_id": conv_id, "answer_id": answer_id,
        "scope": list(scope or []), "semantic": bool(semantic),
        "doc_id": "", "withdrawn": False,
    }

    # A document only when there is something to teach. See the module header on "right, not here".
    if verdict != "right" and (rule or correction):
        if not rule:
            rule = kb_store.one_line(correction.splitlines()[0] if correction else "", MAX_RULE)
        doc = kb_store.make_doc(
            title=rule or "Correction",
            body=_body(rule, correction, question, answer, cited_by_id, superseded),
            folder=FOLDER, kind="feedback", source="feedback", owner=actor,
            trust=kb_store.TRUST_VERIFIED)
        doc["supersedes"] = superseded
        doc["feedback_id"] = rec["id"]
        kb_index.reindex_document(doc)
        rec["doc_id"] = doc["id"]
        rec["rule"] = rule
        log.info("kb_feedback: %s promoted to document %s (supersedes %d)",
                 rec["id"], doc["id"], len(superseded))

    kb_store.write_feedback(rec)
    return rec


def withdraw(fb_id, actor, *, is_staff=False):
    """Take a correction back. The document it produced is ARCHIVED, not deleted: it leaves search
    and stays readable, so a decision that turns out to have been right can be restored and so the
    record of what was believed when is never lost.

    🔴 OWNERSHIP IS ONLY MEANINGFUL FOR AN EMAIL SIGN-IN. A shared password identifies a tier, so
    everybody on that tier shares one actor string and can withdraw each other's corrections. The
    UI says so; pretending otherwise would be the lie.
    """
    rec = kb_store.read_feedback(fb_id)
    if not rec:
        return None, "No such feedback."
    if rec.get("actor") != actor and not is_staff:
        return None, "That correction was left by somebody else."
    if rec.get("doc_id"):
        doc = kb_store.read_doc(rec["doc_id"])
        if doc:
            doc["archived"] = True
            doc["updated_at"] = kb_store.now()
            doc["updated_by"] = actor
            chunks = kb_store.read_chunks(doc["id"]) or {"chunks": [], "model": ""}
            kb_store.write_chunks(doc, chunks["chunks"], model=chunks.get("model") or "")
            kb_store.write_doc(doc)
            kb_index.invalidate()
    rec["withdrawn"] = True
    rec["withdrawn_at"] = kb_store.now()
    rec["withdrawn_by"] = actor
    kb_store.write_feedback(rec)
    return rec, ""


def recent(limit=200):
    return [r for r in kb_store.list_feedback(limit)]


def summary(records=None):
    """Counts for the Observability page. Withdrawn corrections are counted separately rather than
    dropped: "four corrections, one withdrawn" is a more honest picture than "three"."""
    rows = records if records is not None else recent()
    live = [r for r in rows if not r.get("withdrawn")]
    return {
        "total": len(rows),
        "withdrawn": sum(1 for r in rows if r.get("withdrawn")),
        "right": sum(1 for r in live if r.get("verdict") == "right"),
        "elsewhere": sum(1 for r in live if r.get("verdict") == "elsewhere"),
        "wrong": sum(1 for r in live if r.get("verdict") == "wrong"),
        "promoted": sum(1 for r in live if r.get("doc_id")),
        "superseding": sum(1 for r in live if r.get("superseded")),
    }
