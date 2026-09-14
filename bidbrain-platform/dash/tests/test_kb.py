"""Every gate on the knowledge base, and the document API end to end.

RUN IT:
    cd bidbrain-platform\\dash
    ..\\..\\.venv\\Scripts\\python.exe -m pytest tests -q

🔴 THESE TESTS TOUCH REAL GCS, under `kb-test/` in the platform bucket, and wipe it before and
after. That is deliberate: the whole design rests on GCS object generations behaving the way the
index assumes, and a fake storage layer would test the fake. Nothing under `kb/` is read or
written. `ALLOW_PROD_MUTATIONS=1` is set because the app refuses production writes from a local
run, which is exactly the guard these exercise around.

The registry runs on `PLATFORM_BACKEND=memory`, so no real passwords or agencies are involved:
sessions are set directly, which is also the only way to test a session kind that has no password.
"""
import os
import sys
import uuid

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

os.environ.setdefault("PLATFORM_BACKEND", "memory")
os.environ.setdefault("SESSION_SECRET", "test-session")
os.environ.setdefault("SSO_SECRET", "test-sso")
os.environ.setdefault("COOKIE_DOMAIN", "")
os.environ.setdefault("GCS_BUCKET", "bidbrain-analytics-platform-dash")
os.environ.setdefault("KB_VERTEX_PROJECT", "bidbrain-analytics")
os.environ["KB_PREFIX"] = "kb-test-" + uuid.uuid4().hex[:6]
# The app blocks production mutations from a local run. These tests ARE a local run, and they write
# only into their own throwaway prefix.
os.environ["ALLOW_PROD_MUTATIONS"] = "1"

import kb_index      # noqa: E402
import kb_store      # noqa: E402
import main          # noqa: E402

PDF_BYTES = None


def _tiny_pdf():
    """A one page PDF with real extractable text, built by hand so the test needs no fixture file
    and no PDF writer. Hand-built because a fixture binary in the repo is a thing nobody can read
    in a diff."""
    text = "BT /F1 12 Tf 72 720 Td (Northbourne measurable budget is A$188,500) Tj ET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        "<< /Length %d >>\nstream\n%s\nendstream" % (len(text), text),
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = "%PDF-1.4\n"
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += "%d 0 obj\n%s\nendobj\n" % (i, o)
    start = len(out)
    out += "xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += "%010d 00000 n \n" % off
    out += ("trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objs) + 1, start))
    return out.encode("latin-1")


def _wipe():
    from google.cloud import storage
    cl = storage.Client()
    n = 0
    for b in cl.list_blobs(kb_store.bucket_name(), prefix=os.environ["KB_PREFIX"] + "/"):
        b.delete()
        n += 1
    return n


@pytest.fixture(scope="session", autouse=True)
def _clean_prefix():
    _wipe()
    yield
    _wipe()


@pytest.fixture
def client():
    main.app.config["TESTING"] = True
    with main.app.test_client() as c:
        yield c


def _as(c, **sess):
    with c.session_transaction() as s:
        s.clear()
        s.update(sess)


def _staff(c):
    _as(c, kind="superadmin")


def _x100(c):
    _as(c, kind="agency", agency_slug="x100-digital")


# --- §3, the access table, one test per row --------------------------------------------------

GATED = [
    ("GET", "/kb/tree"), ("GET", "/kb/docs"), ("GET", "/kb/status"),
    ("POST", "/kb/docs"), ("POST", "/kb/search"), ("POST", "/kb/upload"),
    ("GET", "/kb/docs/d_1_aaaaaaaa"), ("DELETE", "/kb/docs/d_1_aaaaaaaa"),
    ("POST", "/kb/docs/d_1_aaaaaaaa/move"), ("GET", "/kb/file/d_1_aaaaaaaa"),
    ("POST", "/kb/folder/rename"), ("POST", "/kb/folder/delete"),
    ("POST", "/kb/ask"), ("GET", "/kb/chats"), ("GET", "/kb/chats/c_1_aaaaaaaa"),
    ("DELETE", "/kb/chats/c_1_aaaaaaaa"), ("POST", "/kb/feedback"), ("GET", "/kb/feedback"),
    ("POST", "/kb/feedback/f_1_aaaaaaaa/withdraw"),
    # Staff only, so these are in BOTH lists: denied to everybody below staff, and separately
    # denied to the 100% Digital session that passes every other gate on this page.
    ("GET", "/kb/obs/data"), ("POST", "/kb/obs/probe"), ("POST", "/kb/obs/reach"),
]

STAFF_ONLY = [("GET", "/kb/obs/data"), ("POST", "/kb/obs/probe"), ("POST", "/kb/obs/reach")]


def _call(c, method, path):
    return c.open(path, method=method, json={} if method in ("POST", "PATCH") else None)


@pytest.mark.parametrize("method,path", GATED)
def test_logged_out_is_401_not_a_silent_empty(client, method, path):
    """🔴 An auth failure must be DISTINGUISHABLE. 401 with reason="auth" is what lets the UI say
    "sign in again" instead of "try again", which is the one advice that can never work."""
    _as(client)
    r = _call(client, method, path)
    assert r.status_code == 401, path
    assert r.get_json()["reason"] == "auth"


@pytest.mark.parametrize("method,path", GATED)
def test_a_client_session_gets_403(client, method, path):
    _as(client, kind="client", client_key="geocon")
    r = _call(client, method, path)
    assert r.status_code == 403, path
    assert r.get_json()["reason"] == "forbidden"


@pytest.mark.parametrize("method,path", GATED)
def test_another_agency_gets_403(client, method, path):
    """Transmission is an INTERNAL agency and still has no knowledge base. The gate is one agency
    plus staff, not "anybody we trust"."""
    _as(client, kind="agency", agency_slug="transmission")
    r = _call(client, method, path)
    assert r.status_code == 403, path


def test_an_external_agency_is_denied_before_the_blueprint_even_runs(client):
    """Extrablack is external, so main's deny-by-default `before_request` refuses any endpoint not
    on the allowlist. 🔴 The knowledge base is protected by NOT being on that list, which is why
    `kb.*` must never be added to `_EXTERNAL_ALLOWED_ENDPOINTS`."""
    _as(client, kind="agency", agency_slug="extrablack")
    r = client.get("/kb/tree")
    assert r.status_code == 403
    assert "Not available" in r.get_json()["error"]


def test_staff_and_x100_are_allowed(client):
    _staff(client)
    assert client.get("/kb/tree").status_code == 200
    _x100(client)
    assert client.get("/kb/tree").status_code == 200


def test_a_staff_member_inside_another_agency_portal_is_still_staff(client):
    """/enter-agency flips session["kind"] to "agency" and stashes the real role in admin_return.
    `_kb_allowed` reads `_admin_kind()` for exactly this case."""
    _as(client, kind="agency", agency_slug="transmission", admin_return="superadmin")
    assert client.get("/kb/tree").status_code == 200


@pytest.mark.parametrize("method,path", STAFF_ONLY)
def test_observability_is_staff_only_even_for_the_agency_that_owns_the_library(client, method, path):
    """🔴 100% Digital may read the library, ask it and correct it. The page listing every question
    anybody has asked is ours. The ROUTE enforces that; hiding the nav link would not."""
    _x100(client)
    assert client.get("/kb/tree").status_code == 200, "the same session must pass the normal gate"
    r = _call(client, method, path)
    assert r.status_code == 403, path
    _staff(client)
    assert _call(client, method, path).status_code == 200, path


def test_the_observability_PAGE_is_staff_only_too(client):
    _x100(client)
    assert client.get("/kb/").status_code == 200
    assert client.get("/kb/observability").status_code == 403
    _staff(client)
    assert client.get("/kb/observability").status_code == 200


def test_the_page_route_sends_a_logged_out_visitor_to_login_not_to_a_403(client):
    _as(client)
    r = client.get("/kb/")
    assert r.status_code == 302 and r.headers["Location"].endswith("/")


# --- the document API, end to end ---------------------------------------------------------------

def test_create_read_move_search_and_delete(client):
    _staff(client)
    r = client.post("/kb/docs", json={
        "title": "Rate card rationale",
        "body": "The margin floor is forty per cent.\n\nBelow that we decline the work.\n",
        "folder": "Playbook", "kind": "reference"})
    assert r.status_code == 200, r.get_data(as_text=True)
    doc = r.get_json()["doc"]
    assert doc["folder"] == "Playbook" and doc["chunks"] >= 1

    got = client.get("/kb/docs/%s" % doc["id"]).get_json()
    assert got["ok"] and "margin floor" in got["doc"]["body"]
    assert got["passages"] and got["passages"][0]["text"]

    assert client.post("/kb/docs/%s/move" % doc["id"],
                       json={"folder": "Playbook/Pricing"}).get_json()["folder"] == "Playbook/Pricing"
    rows = client.get("/kb/docs?folder=Playbook/Pricing").get_json()["docs"]
    assert [d["id"] for d in rows] == [doc["id"]]
    # The parent folder does NOT list it without deep=1, and DOES with it. That is what a tree
    # means: a folder shows its own documents, and ticking it in the picker includes everything
    # below.
    assert client.get("/kb/docs?folder=Playbook").get_json()["docs"] == []
    assert len(client.get("/kb/docs?folder=Playbook&deep=1").get_json()["docs"]) == 1

    s = client.post("/kb/search", json={"q": "what is the margin floor"}).get_json()
    assert s["ok"] and s["excerpts"] and s["excerpts"][0]["document_id"] == doc["id"]
    assert s["outcome"]

    assert client.delete("/kb/docs/%s" % doc["id"]).status_code == 200
    assert client.delete("/kb/docs/%s" % doc["id"]).status_code == 404


def test_edit_writes_a_revision_and_a_stale_generation_is_refused(client):
    _staff(client)
    doc = client.post("/kb/docs", json={"title": "Flight dates", "body": "Starts 1 July.",
                                        "folder": "Media plans"}).get_json()["doc"]
    full = client.get("/kb/docs/%s" % doc["id"]).get_json()["doc"]
    gen = full["generation"]
    r = client.patch("/kb/docs/%s" % doc["id"],
                     json={"body": "Starts 3 July.", "generation": gen, "note": "corrected"})
    assert r.status_code == 200
    after = client.get("/kb/docs/%s" % doc["id"]).get_json()["doc"]
    assert after["revisions"] == 1 and after["revision_list"][0]["note"] == "corrected"

    # 🔴 The SAME generation again must now fail. A lost update here is somebody's edit vanishing
    # with no error, which is the failure nobody reports because nobody sees it.
    stale = client.patch("/kb/docs/%s" % doc["id"], json={"body": "Starts 9 July.",
                                                          "generation": gen})
    assert stale.status_code == 409 and stale.get_json()["reason"] == "conflict"
    client.delete("/kb/docs/%s" % doc["id"])


def test_upload_a_pdf_and_a_markdown_file(client):
    _staff(client)
    import io
    data = {
        "folder": "Media plans",
        "file": [(io.BytesIO(_tiny_pdf()), "Northbourne plan v3.pdf"),
                 (io.BytesIO(b"# Ritual\n\nThe reviewer is never the author.\n"), "ritual.md")],
    }
    r = client.post("/kb/upload", data=data, content_type="multipart/form-data")
    assert r.status_code == 200, r.get_data(as_text=True)
    j = r.get_json()
    assert j["ok"] and len(j["docs"]) == 2 and not j["failed"]
    by_title = {d["title"]: d for d in j["docs"]}
    # The file NAME is the title, not the first line of the PDF.
    assert "Northbourne plan v3" in by_title
    pdf = by_title["Northbourne plan v3"]
    assert pdf["source"] == "upload" and pdf["chunks"] >= 1

    # The original is kept, byte for byte, and downloadable.
    f = client.get("/kb/file/%s" % pdf["id"])
    assert f.status_code == 200 and f.data[:5] == b"%PDF-"
    assert "attachment" in f.headers["Content-Disposition"]

    s = client.post("/kb/search", json={"q": "Northbourne measurable budget"}).get_json()
    assert any(e["document_id"] == pdf["id"] for e in s["excerpts"]), \
        "the PDF's text did not reach the index"
    for d in j["docs"]:
        client.delete("/kb/docs/%s" % d["id"])


def test_an_unreadable_file_is_refused_and_not_stored(client):
    """🔴 Refusing is loud; storing mojibake is silent. A .docx indexed as prose looks exactly like
    a document that is simply never relevant."""
    _staff(client)
    import io
    before = len(client.get("/kb/docs").get_json()["docs"])
    r = client.post("/kb/upload", content_type="multipart/form-data", data={
        "file": (io.BytesIO(b"PK\x03\x04" + b"\x00" * 200), "brief.docx")})
    assert r.status_code == 400
    assert "Word" in r.get_json()["failed"][0]["error"]
    assert len(client.get("/kb/docs").get_json()["docs"]) == before


def test_scope_narrows_before_scoring(client):
    _staff(client)
    a = client.post("/kb/docs", json={"title": "Pricing", "body": "The margin floor is forty.",
                                      "folder": "Playbook"}).get_json()["doc"]
    b = client.post("/kb/docs", json={"title": "Plan", "body": "The flight starts in July.",
                                      "folder": "Media plans"}).get_json()["doc"]
    s = client.post("/kb/search", json={"q": "margin floor", "folders": ["Media plans"]}).get_json()
    assert s["documents_searched"] == 1, "scope must narrow the candidates, not the results"
    assert all(e["document_id"] == b["id"] for e in s["excerpts"])
    s2 = client.post("/kb/search", json={"q": "margin floor",
                                         "folders": ["Nowhere"]}).get_json()
    assert s2["excerpts"] == [] and "no documents" in s2["outcome"]
    for d in (a, b):
        client.delete("/kb/docs/%s" % d["id"])


def test_a_folder_that_still_holds_documents_is_not_deleted(client):
    _staff(client)
    d = client.post("/kb/docs", json={"title": "x", "body": "y", "folder": "Temp/Deep"}) \
        .get_json()["doc"]
    r = client.post("/kb/folder/delete", json={"path": "Temp"})
    assert r.status_code == 409 and r.get_json()["count"] == 1
    assert client.post("/kb/folder/rename", json={"from": "Temp", "to": "Kept"}) \
        .get_json()["moved"] == 1
    assert client.get("/kb/docs/%s" % d["id"]).get_json()["doc"]["folder"] == "Kept/Deep"
    assert client.post("/kb/folder/rename", json={"from": "Kept", "to": "Kept/Inner"}) \
        .status_code == 400, "a folder cannot be moved inside itself"
    client.delete("/kb/docs/%s" % d["id"])


# --- the assistant editing documents --------------------------------------------------------------

def test_append_adds_a_dated_section_and_records_who_and_when(client):
    """🔴 The assistant's ONE write verb, and the metadata is the point of it. A change has to say
    WHEN it happened, WHO stands behind it, and that the assistant drafted it, or nobody can judge
    a paragraph they did not write."""
    _staff(client)
    doc = client.post("/kb/docs", json={
        "title": "Rate card rationale", "folder": "Playbook",
        "body": "The margin floor is forty per cent."}).get_json()["doc"]

    r = client.post("/kb/docs/%s/append" % doc["id"], json={
        "heading": "Q3 rate review", "text": "The floor rose to fifty per cent from Q3.",
        "note": "Record the Q3 floor", "via": "assistant"})
    assert r.status_code == 200

    full = client.get("/kb/docs/%s" % doc["id"]).get_json()["doc"]
    # 🔴 APPEND CANNOT LOSE TEXT. The original sentence is still there, which is the whole reason
    # this is the only verb the assistant gets.
    assert "The margin floor is forty per cent." in full["body"]
    assert "## Q3 rate review (" in full["body"]
    assert "rose to fifty per cent" in full["body"]

    rev = full["revision_list"][0]
    assert rev["via"] == "assistant", "an assistant draft must be marked as one"
    assert rev["by"], "a change with no author is not an audit trail"
    assert rev["at"] > 0
    assert rev["note"] == "Record the Q3 floor", "the note must be the line the person approved"
    assert full["updated_by"] == rev["by"]
    assert full["updated_at"] >= rev["at"]

    # The appended text is searchable at once, not on some later pass.
    s = client.post("/kb/search", json={"q": "when did the floor rise to fifty"}).get_json()
    assert any("fifty per cent from Q3" in e["passage"] for e in s["excerpts"])

    # And it is undoable, with the undo itself recorded.
    client.post("/kb/docs/%s/restore" % doc["id"], json={"index": 0})
    back = client.get("/kb/docs/%s" % doc["id"]).get_json()["doc"]
    assert "Q3 rate review" not in back["body"]
    assert back["revisions"] == 2, "history must never lose a branch"
    assert back["revision_list"][1]["via"] == "assistant", "the AI edit stays in the record"
    client.delete("/kb/docs/%s" % doc["id"])


def test_append_refuses_what_it_should(client):
    _staff(client)
    doc = client.post("/kb/docs", json={"title": "T", "body": "b"}).get_json()["doc"]
    assert client.post("/kb/docs/%s/append" % doc["id"], json={"text": "  "}).status_code == 400
    assert client.post("/kb/docs/d_0_nosuchxx/append", json={"text": "x"}).status_code == 404
    client.patch("/kb/docs/%s" % doc["id"], json={"archived": True})
    r = client.post("/kb/docs/%s/append" % doc["id"], json={"text": "x"})
    assert r.status_code == 409, "an archived document is out of the library, not a write target"
    client.delete("/kb/docs/%s" % doc["id"])


def test_a_metadata_only_patch_is_actually_saved(client):
    """🔴 THE REGRESSION. `reindex_document` short-circuits when the TEXT is unchanged, and it used
    to return before writing anything, so a PATCH that only set `archived`, `trust` or `kind` was
    silently discarded. The Explorer's Archive button appeared to work and did nothing. Found by a
    test aiming at something else, which is the only reason it was found at all."""
    _staff(client)
    doc = client.post("/kb/docs", json={"title": "Meta only", "body": "unchanging text",
                                        "folder": "Playbook"}).get_json()["doc"]
    for field, value in (("archived", True), ("trust", "verified"), ("kind", "plan")):
        client.patch("/kb/docs/%s" % doc["id"], json={field: value})
        got = client.get("/kb/docs/%s" % doc["id"]).get_json()["doc"]
        assert got[field] == value, "%s did not persist" % field
    # And the index agrees: archived means out of search, not merely flagged.
    s = client.post("/kb/search", json={"q": "unchanging text"}).get_json()
    assert all(e["document_id"] != doc["id"] for e in s["excerpts"])
    client.delete("/kb/docs/%s" % doc["id"])


def test_an_edit_by_a_person_is_not_labelled_as_the_assistant(client):
    """The `via` field is how the history pane distinguishes them. Defaulting it to "assistant"
    would put the AI's name on somebody's own writing."""
    _staff(client)
    doc = client.post("/kb/docs", json={"title": "T", "body": "b"}).get_json()["doc"]
    client.post("/kb/docs/%s/append" % doc["id"], json={"text": "typed by a person"})
    full = client.get("/kb/docs/%s" % doc["id"]).get_json()["doc"]
    assert full["revision_list"][0]["via"] == "human"
    client.delete("/kb/docs/%s" % doc["id"])


def test_the_proposal_block_never_survives_into_stored_text(client):
    """🔴 Stripped wherever the answer is kept or reused. Fed back as a prior turn, a block also
    teaches the model that emitting one is simply how answers look, which is how proposals start
    appearing on questions that settle nothing."""
    import kb_prompt
    prose, proposed = kb_prompt.strip_proposal(
        'Here is the answer [1].\n\n```bb-edit\n{"action":"append","passage":1,"text":"x"}\n```')
    assert prose == "Here is the answer [1]." and proposed is True
    prose2, proposed2 = kb_prompt.strip_proposal("Just an answer.")
    assert prose2 == "Just an answer." and proposed2 is False
    # An unterminated block (the stream was stopped mid-proposal) is still cut.
    prose3, proposed3 = kb_prompt.strip_proposal('Answer.\n\n```bb-edit\n{"action":"app')
    assert prose3 == "Answer." and proposed3 is False


def test_the_prompt_tells_the_model_the_real_folders_and_the_real_rules(client):
    import kb_prompt
    p = kb_prompt.prefix([{"title": "A", "folder": "Playbook", "passage": "x", "trust": "standard"}],
                         folders=["Playbook", "Media plans"])
    assert "```bb-edit" in p
    assert "- Playbook" in p and "- Media plans" in p, "a create proposal must name a real folder"
    assert "You cannot rewrite, replace" in p
    assert "never a title and never an id" in p or "never name" in p


# --- the feedback loop ---------------------------------------------------------------------------

def test_a_correction_outranks_the_passage_it_corrects_and_withdrawing_undoes_it(client):
    """§8 in one test, because the pieces only mean anything together.

    🔴 The assertion is on the RANKING, not on the document existing. A correction that is filed
    and does not outrank what it corrects has not been learned, which is the whole point of the
    loop.
    """
    _staff(client)
    doc = client.post("/kb/docs", json={
        "title": "Rate card rationale", "folder": "Playbook",
        "body": "The margin floor is forty per cent.\n\nBelow that we decline the work."
    }).get_json()["doc"]

    before = client.post("/kb/search", json={"q": "what is the margin floor"}).get_json()
    top = before["excerpts"][0]
    assert top["document_id"] == doc["id"]
    assert top["trust"] == "standard"

    fb = client.post("/kb/feedback", json={
        "question": "what is the margin floor",
        "answer": "The margin floor is forty per cent [1].",
        "verdict": "wrong",
        "rule": "The margin floor is fifty per cent from Q3, not forty",
        "correction": "It was raised to fifty in the Q3 pricing review.",
        "cited": [{"passage_id": top["passage_id"], "document_id": doc["id"],
                   "title": top["title"], "folder": top["folder"], "trust": "standard"}],
        "superseded": [top["passage_id"]],
    }).get_json()["feedback"]
    assert fb["doc_id"], "a correction with a rule must become a document"

    after = client.post("/kb/search", json={"q": "what is the margin floor"}).get_json()
    assert after["excerpts"][0]["document_id"] == fb["doc_id"]
    assert after["excerpts"][0]["trust"] == "verified"
    corrected = [e for e in after["excerpts"] if e["passage_id"] == top["passage_id"]]
    assert corrected, "the corrected passage must still be findable, just lower"
    assert corrected[0]["score"] < top["score"], "the superseded passage was not demoted"
    # 🔴 And the original document is UNCHANGED. A correction is never written into the thing it
    # corrects: two documents that disagree is the true state of the world.
    assert "forty per cent" in client.get("/kb/docs/%s" % doc["id"]).get_json()["doc"]["body"]

    # A verified document does not win a question it has nothing to do with.
    other = client.post("/kb/docs", json={"title": "Flight window", "folder": "Media plans",
                                          "body": "The Trade Desk line runs from 20 August."}) \
        .get_json()["doc"]
    unrelated = client.post("/kb/search", json={"q": "when does the Trade Desk line start"}).get_json()
    assert unrelated["excerpts"][0]["document_id"] == other["id"], \
        "TRUST_NUDGE is too large: a correction won an unrelated question"

    # Withdrawing archives the document it made, and takes it out of search.
    client.post("/kb/feedback/%s/withdraw" % fb["id"])
    gone = client.post("/kb/search", json={"q": "what is the margin floor"}).get_json()
    assert all(e["document_id"] != fb["doc_id"] for e in gone["excerpts"])
    assert gone["excerpts"][0]["document_id"] == doc["id"], "the original should rank again"
    assert client.get("/kb/docs/%s" % fb["doc_id"]).get_json()["doc"]["archived"] is True

    for d in (doc["id"], other["id"], fb["doc_id"]):
        client.delete("/kb/docs/%s" % d)


def test_right_not_here_records_feedback_without_inventing_a_document(client):
    """A right answer from the wrong citation is a RETRIEVAL problem. Promoting it would file a
    correction that corrects nothing."""
    _staff(client)
    fb = client.post("/kb/feedback", json={
        "question": "anything", "answer": "an answer", "verdict": "elsewhere",
        "rule": "", "correction": "", "cited": [], "superseded": []}).get_json()["feedback"]
    assert fb["verdict"] == "elsewhere" and not fb["doc_id"]


# --- the assistant --------------------------------------------------------------------------------

def test_ask_streams_retrieval_before_it_streams_any_answer(client):
    """🔴 The citations must arrive BEFORE the first token. Appending them afterwards produces the
    same pixels and a different claim: that the model picked them to justify what it had said."""
    _staff(client)
    doc = client.post("/kb/docs", json={"title": "Pace basis", "folder": "Playbook",
                                        "body": "Pacing is drawn against the measurable budget."}) \
        .get_json()["doc"]
    r = client.post("/kb/ask", json={"q": "what is pacing drawn against"})
    assert r.status_code == 200
    assert r.headers["Content-Type"].startswith("text/event-stream")
    body = r.get_data(as_text=True)
    events = [ln[7:].strip() for ln in body.splitlines() if ln.startswith("event:")]
    assert events[0] == "retrieval", events[:4]
    assert "done" in events or "error" in events
    # Whether a model answered depends on a key being present in THIS environment, so the test
    # asserts what must hold either way: retrieval happened and its outcome was declared.
    assert '"outcome"' in body and '"semantic"' in body
    client.delete("/kb/docs/%s" % doc["id"])


def test_a_streamed_question_is_actually_recorded(client):
    """🔴 THE REGRESSION THIS EXISTS FOR. `_log_event` used to read `session` for the actor, and a
    Flask generator outlives the request context, so the call from inside `ask`'s generator raised
    and the blanket except swallowed it. Every question the assistant answered recorded NOTHING
    while uploads and plain searches recorded fine, and the Observability page read "1 question
    asked" after three. Found by counting objects in the bucket, not by trusting the page.
    """
    import kb_activity
    import kb_routes
    _staff(client)

    # The mechanism, outside any request context at all, which is the state the generator is in.
    assert kb_routes._log_event("question", actor="test:harness", query="probe") is None
    with main.app.test_request_context("/kb/"):
        pass
    found = [e for e in kb_activity.recent() if e.get("actor") == "test:harness"]
    assert found, "an event written with an explicit actor and no request context was lost"

    doc = client.post("/kb/docs", json={"title": "Pace basis", "folder": "Playbook",
                                        "body": "Pacing is drawn against the measurable budget."}) \
        .get_json()["doc"]
    before = len([e for e in kb_activity.recent() if e.get("kind") == "question"])
    body = client.post("/kb/ask", json={"q": "what is pacing drawn against"}).get_data(as_text=True)
    if "event: done" in body:
        after = len([e for e in kb_activity.recent() if e.get("kind") == "question"])
        assert after == before + 1, "an answered question left no trace in the usage record"
    client.delete("/kb/docs/%s" % doc["id"])


def test_an_answer_is_kept_as_a_conversation(client):
    _staff(client)
    doc = client.post("/kb/docs", json={"title": "Ritual", "folder": "Playbook",
                                        "body": "The reviewer is never the author."}) \
        .get_json()["doc"]
    client.post("/kb/ask", json={"q": "who reviews the report"}).get_data()
    chats = client.get("/kb/chats").get_json()
    assert chats["ok"]
    if chats["chats"]:                    # only when a model was configured to answer
        cid = chats["chats"][0]["id"]
        full = client.get("/kb/chats/%s" % cid).get_json()["chat"]
        assert full["messages"][0]["role"] == "user"
        assert client.delete("/kb/chats/%s" % cid).get_json()["ok"]
    client.delete("/kb/docs/%s" % doc["id"])


def test_the_prompt_puts_its_blocks_in_the_stated_order(client):
    """The order is the contract (kb_prompt's header), and it is the kind of thing that drifts
    silently when somebody adds a block."""
    import kb_prompt
    p = kb_prompt.prefix([{"title": "A plan", "folder": "Media plans", "passage": "some text",
                           "trust": "standard"}], semantic=True, scope=["Media plans"])
    assert p.index("You are the Bidbrain knowledge assistant") \
        < p.index("HOW THIS KNOWLEDGE BASE WORKS") \
        < p.index("RETRIEVED FROM THE LIBRARY")
    assert "SCOPE: the person has narrowed this search" in p
    assert kb_prompt.guide_text(), "the self-knowledge document must ship in the image"


def test_a_verified_passage_tells_the_model_to_say_whose_correction_it_is(client):
    import kb_prompt
    p = kb_prompt.prefix([{"title": "Fifty per cent", "folder": "Media buyer knowledge",
                           "passage": "fifty", "trust": "verified",
                           "owner": "shared:superadmin", "updated_at": 1789000000}])
    assert "VERIFIED CORRECTION" in p
    # 🔴 The DISPLAY form of the actor, because the model quotes it verbatim into a sentence.
    assert "shared:superadmin" not in p and "superadmin (shared login)" in p


def test_keyword_only_is_declared_in_the_prompt_not_just_in_the_payload(client):
    import kb_prompt
    p = kb_prompt.prefix([], semantic=False, semantic_error="Vertex is off")
    assert "WORDING ONLY" in p and "Vertex is off" in p and "Say so in your answer" in p


def test_the_index_sees_a_write_that_did_not_go_through_this_process(client):
    """The signature is the object listing, so an upload served by another Cloud Run instance is
    visible here without a restart and without anybody calling invalidate()."""
    _staff(client)
    doc = kb_store.make_doc(title="Written elsewhere", body="An out of band document.",
                            folder="Playbook", owner="other-instance")
    kb_index.reindex_document(doc, embed=False)
    kb_index._INDEX._corpus = None            # noqa: SLF001 - stand in for a different process
    kb_index._INDEX._docs = {}                # noqa: SLF001
    rows = client.get("/kb/docs?folder=Playbook").get_json()["docs"]
    assert any(r["id"] == doc["id"] for r in rows)
    # It was written with embed=False, so it is keyword-only AND SAYS SO on its row.
    row = [r for r in rows if r["id"] == doc["id"]][0]
    assert row["state"] == "keyword" and row["state_note"]
    client.delete("/kb/docs/%s" % doc["id"])
