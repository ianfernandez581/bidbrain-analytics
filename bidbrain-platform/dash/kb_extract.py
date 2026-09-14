"""kb_extract.py - an uploaded file into the text the knowledge base can actually retrieve.

The assistant reads nothing it is not handed, and a PDF sitting in a bucket is invisible to it. So
"upload a document" means "extract its text into a document". Unlike the system this is ported
from, the ORIGINAL FILE IS ALSO KEPT (kb_store.write_file): a media plan gets re-opened by a human,
and a human wants the plan, not a transcription of it. The text is what is searched; the file is
what is downloaded.

🔴 AN UNREADABLE FILE IS REFUSED, NEVER STORED AS MOJIBAKE. A .docx or a scanned PDF decoded as
"text" produces a page of replacement characters that indexes perfectly happily, matches nothing a
person would ever search for, and looks like a document that is simply never relevant. Refusing is
loud; storing the mojibake is silent, and silence is the failure nobody reports.

🔴 A CUT IS DECLARED IN THE TEXT ITSELF. A PDF longer than the ceiling is truncated and the notice
is written into the body, in words the model will read, so a miss reads as "I do not have that
part" rather than "that part does not exist".

`pypdf` is imported lazily, so an image built without it still boots and only PDF upload reports
itself unavailable.
"""
import io
import os
import re

# The indexable ceiling for one document. Generous: a 200-page handbook still lands whole.
MAX_CHARS = 400_000
# Upload ceiling. Text-heavy PDFs are small; much bigger is almost certainly scanned images, which
# yield no text anyway. Note the app's own MAX_CONTENT_LENGTH is the outer bound.
MAX_UPLOAD_BYTES = 15 * 1024 * 1024

# What we will try to read as text. Everything else is refused BY NAME, so the message can say what
# to do instead.
TEXT_EXTS = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".log", ".rst", ".yaml", ".yml"}
PDF_EXTS = {".pdf"}
# Formats people will certainly try, named so the refusal is useful rather than generic.
KNOWN_UNSUPPORTED = {
    ".docx": "Word files are not read yet. Save as PDF, or paste the text.",
    ".doc": "Word files are not read yet. Save as PDF, or paste the text.",
    ".xlsx": "Spreadsheets are not read yet. Export the sheet as CSV.",
    ".xls": "Spreadsheets are not read yet. Export the sheet as CSV.",
    ".pptx": "Slide decks are not read yet. Export as PDF.",
    ".ppt": "Slide decks are not read yet. Export as PDF.",
    ".zip": "Archives are not read. Upload the files inside it.",
}


class ExtractError(ValueError):
    """The file could not be turned into text. The message is shown to the person who uploaded it."""


def ext_of(filename):
    return os.path.splitext((filename or "").strip().lower())[1]


def _looks_binary(data):
    """A NUL byte or a wall of unprintables in the first block. Cheap, and it is the difference
    between refusing a .docx and indexing its zip container as prose."""
    head = data[:8192]
    if b"\x00" in head:
        return True
    if not head:
        return False
    printable = sum(1 for b in head if 9 <= b <= 13 or 32 <= b <= 126 or b >= 160)
    return (printable / len(head)) < 0.85


def _decode(data):
    """UTF-8, then UTF-16 (what Windows Notepad and many exports produce), then cp1252. A file that
    survives none of them is refused rather than mangled."""
    for enc in ("utf-8-sig", "utf-8", "utf-16", "cp1252"):
        try:
            text = data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
        if "�" not in text:
            return text
    raise ExtractError("That file is not readable as text. If it is a Word or Excel file, "
                       "export it as PDF or CSV first.")


def extract_pdf(data, max_chars=MAX_CHARS):
    """-> (text, note, pages, pages_imported). Page markers stay in: `[page 12]` lines let an answer
    say WHERE in a document something is, and cost almost nothing."""
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError as e:                       # pragma: no cover - depends on the image
        raise ExtractError("PDF reading is not available on this server") from e
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            # Many "encrypted" PDFs only restrict printing and open with an empty password.
            try:
                if not reader.decrypt(""):
                    raise ExtractError("That PDF is password protected. Remove the password and "
                                       "try again.")
            except ExtractError:
                raise
            except Exception as e:                 # noqa: BLE001 - pypdf raises a mix of types
                raise ExtractError("That PDF is password protected. Remove the password and try "
                                   "again.") from e
        total = len(reader.pages)
    except ExtractError:
        raise
    except Exception as e:                         # noqa: BLE001
        raise ExtractError("That file does not look like a readable PDF") from e

    parts, used, imported, truncated = [], 0, 0, False
    for i in range(total):
        try:
            page_text = (reader.pages[i].extract_text() or "").strip()
        except Exception:                          # noqa: BLE001 - one bad page must not sink the file
            page_text = ""
        if not page_text:
            continue
        block = "[page %d]\n%s" % (i + 1, page_text)
        if used + len(block) > max_chars and parts:
            truncated = True
            break
        if len(block) > max_chars:
            block = block[:max_chars]
            truncated = True
        parts.append(block)
        used += len(block) + 2
        imported += 1
        if truncated:
            break

    if not parts:
        raise ExtractError("No readable text in that PDF. If it is a scan, it has no text layer "
                           "to import.")
    text = "\n\n".join(parts)
    note = ""
    if truncated:
        left = total - imported
        note = ("this PDF was cut to fit: %d more page%s (%d in total) were NOT imported"
                % (left, "" if left == 1 else "s", total))
        text += ("\n\n[Import note: %s. Anything past this point is unknown, not absent.]" % note)
    return text, note, total, imported


def extract(filename, data, *, mime=""):
    """-> {text, note, kind_hint, pages}. Raises ExtractError with a message meant for a person."""
    if not data:
        raise ExtractError("That file is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ExtractError("That file is %.1f MB. The limit is %d MB."
                           % (len(data) / 1048576.0, MAX_UPLOAD_BYTES // 1048576))
    ext = ext_of(filename)
    if ext in KNOWN_UNSUPPORTED:
        raise ExtractError(KNOWN_UNSUPPORTED[ext])
    if ext in PDF_EXTS or (mime or "").lower() == "application/pdf" or data[:5] == b"%PDF-":
        text, note, pages, imported = extract_pdf(data)
        return {"text": text, "note": note, "kind_hint": "reference", "pages": pages,
                "pages_imported": imported}
    if ext in TEXT_EXTS or (mime or "").lower().startswith("text/"):
        if _looks_binary(data):
            raise ExtractError("That file says it is text but does not read as text. It was not "
                               "stored, because a file of replacement characters would index as a "
                               "document that is simply never relevant.")
        text = _decode(data)
        if not text.strip():
            raise ExtractError("That file has no text in it")
        note = ""
        if len(text) > MAX_CHARS:
            over = len(text) - MAX_CHARS
            text = text[:MAX_CHARS] + ("\n\n[Import note: this file was cut to fit: %d more "
                                       "characters were NOT imported.]" % over)
            note = "cut to fit: %d characters were not imported" % over
        return {"text": text, "note": note, "kind_hint": "reference", "pages": 0,
                "pages_imported": 0}
    raise ExtractError("%s files are not read. Upload a PDF, or a text, Markdown or CSV file, or "
                       "paste the text." % (ext.lstrip(".").upper() or "Those"))


def title_for(filename, text):
    """A document title from the file. The file NAME wins: somebody chose it, and a PDF's first
    line is as often a logo caption or a page number as it is a title."""
    base = os.path.basename((filename or "").strip())
    stem = os.path.splitext(base)[0].strip()
    stem = re.sub(r"[_]+", " ", stem)
    stem = re.sub(r"\s{2,}", " ", stem).strip()
    if stem:
        return stem[:300]
    for line in (text or "").splitlines():
        t = line.strip().lstrip("#").strip()
        if t and not t.startswith("[page "):
            return t[:120]
    return "Untitled"
