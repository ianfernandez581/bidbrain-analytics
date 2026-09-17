"""What kb_repo_sync must never get wrong, over the REAL repo.

RUN IT:
    .\\.venv\\Scripts\\python.exe -m pytest scripts\\test_kb_repo_sync.py -q

No credentials, no network, no bucket: every test here is over the planning half of the sync, which
is pure. The write half is exercised by running it with --dry-run, and the storage layer it writes
through has its own tests in bidbrain-platform/dash/tests/test_kb.py.

🔴 THE FIRST TEST IS THE ONE THAT MATTERS. A splitter that drops a section does not fail, warn, or
look any different: the library simply has no passage about that thing, and the assistant answers
"there is nothing about that" in the same voice it uses when it is right. Nothing else in this
system can detect it, so it is asserted at word level, over all 164 files, every run.
"""
import collections
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import kb_repo_sync as S      # noqa: E402
import kb_store               # noqa: E402


@pytest.fixture(scope="module")
def docs():
    return S.plan_documents()


def body_only(doc):
    """A document's text without the breadcrumb this script adds."""
    return doc["body"].split("\n\n", 1)[1]


def test_not_one_word_of_the_repo_is_lost():
    for rel in S.tracked_markdown():
        text = S.read_text(rel)
        if not text.strip():
            continue
        have = collections.Counter()
        for doc in S.plan_documents([rel]):
            have.update(body_only(doc).split())
        missing = collections.Counter(text.split()) - have
        assert not missing, "%s loses %d words, e.g. %r" % (
            rel, sum(missing.values()), list(missing)[:5])


def test_every_id_is_unique_and_legal(docs):
    ids = collections.Counter(d["id"] for d in docs)
    clashes = {i: n for i, n in ids.items() if n > 1}
    # A clash is silent data loss: two sections would write to one document, last one wins.
    assert not clashes, clashes
    assert all(re.match(r"^[A-Za-z0-9_-]{3,64}$", d["id"]) for d in docs)
    assert all(d["id"].startswith(S.ID_PREFIX) for d in docs)


def test_ids_are_stable_across_runs(docs):
    # The whole difference between a sync and an import. If this fails, every run creates a second
    # copy of the library beside the first.
    assert [d["id"] for d in S.plan_documents()] == [d["id"] for d in docs]


def test_a_windows_checkout_reads_exactly_like_a_linux_one(tmp_path, monkeypatch):
    """Git gives CRLF on Windows and LF in CI. The ids survive that either way, but the CONTENT
    HASH does not - so without this normalisation every run from the other platform rewrites and
    re-embeds all 164 files to change nothing. Asserted at the read, which is the only place it is
    done."""
    monkeypatch.setattr(S, "REPO", str(tmp_path))
    (tmp_path / "crlf.md").write_bytes(b"# A\r\n\r\nline one\r\nline two\r\n")
    (tmp_path / "lf.md").write_bytes(b"# A\n\nline one\nline two\n")
    assert S.read_text("crlf.md") == S.read_text("lf.md") == "# A\n\nline one\nline two\n"
    # A BOM is the other thing a Windows editor leaves behind.
    (tmp_path / "bom.md").write_bytes(b"\xef\xbb\xbf# A\r\n")
    assert S.read_text("bom.md") == "# A\n"


def test_no_carriage_return_reaches_a_document(docs):
    assert not [d["title"] for d in docs if "\r" in d["body"]]


def test_titles_are_unique_and_name_their_source(docs):
    titles = collections.Counter(d["title"] for d in docs)
    assert not [t for t, n in titles.items() if n > 1]
    for d in docs:
        assert d["title"].startswith(d["rel"])
        assert len(d["title"]) <= kb_store.MAX_TITLE_CHARS
        assert "\n" not in d["title"]


def test_nothing_is_left_too_big_to_be_citable(docs):
    # kb_index.MAX_PER_DOC is 2, so an oversized document is mostly unreachable text.
    over = [(d["title"], len(d["body"])) for d in docs
            if len(d["body"]) > S.MAX_DOC_CHARS + 1_000]
    assert not over, over[:3]


def test_every_client_row_of_the_agents_table_is_its_own_document(docs):
    """The row split, asserted by what it must ADMIT rather than by a count that drifts."""
    titles = [d["title"] for d in docs if d["title"].startswith("md/AGENTS.md > The clients >")]
    for client in ("mongodb", "cloudflare", "schneider", "geocon", "sophiie", "caltex", "vmch"):
        named = [t for t in titles if t.split(" > ")[2] == client]
        assert named, "no document for the %s row" % client
        # One client per document: a title may name a part, never a second client.
        assert all(len(t.split(" > ")) <= 4 for t in named), named


def test_folders_mirror_the_repo_and_sit_under_one_top_folder(docs):
    for d in docs:
        assert d["folder"] == d["folder"].strip("/")
        assert d["folder"] == S.TOP_FOLDER or d["folder"].startswith(S.TOP_FOLDER + "/")
        assert d["folder"] == kb_store.normalize_folder(d["folder"])
    by_rel = {d["rel"]: d["folder"] for d in docs}
    assert by_rel["md/AGENTS.md"] == "GCP Backend/md"
    assert by_rel["README.md"] == "GCP Backend"
    assert by_rel["clients/client_geocon/dash/README.md"] == \
        "GCP Backend/clients/client_geocon/dash"


def test_a_heading_inside_a_code_fence_is_not_a_heading():
    text = ("# Real\n\nbefore\n\n```sh\n## not a heading\n```\n\nafter\n\n## Also real\n\nx\n")
    assert [t for _, t, _ in S.outline(text) if t] == ["Real", "Also real"]


def test_the_breadcrumb_carries_no_commit_or_timestamp(docs):
    # Either would change the body on every run, re-embedding the library to say nothing new.
    for d in docs[:50]:
        head = d["body"].split("\n\n", 1)[0]
        assert not re.search(r"\b[0-9a-f]{7,40}\b", head)
        assert not re.search(r"\b20\d\d-\d\d-\d\d\b", head)


def test_only_tracked_files_are_ever_read(monkeypatch):
    # An untracked scratch note must not be able to reach the library.
    real = S.git
    monkeypatch.setattr(S, "git", lambda *a: "md/AGENTS.md\nsecret-scratch.md\n" if a[0] == "ls-files"
                        else real(*a))
    assert S.tracked_markdown(["md/*.md"]) == ["md/AGENTS.md"]
