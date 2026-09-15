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
itself unavailable. The same goes for `python-docx`, `python-pptx` and `openpyxl` (2026-09-15: Word,
PowerPoint, Excel and WebVTT/SRT transcripts are read too, ported from the RAG branch's
knowledge_parse.py). Each format writes its own locator into the text the way PDF writes `[page N]`:
`[slide N]`, `[sheet Name]`, `[table N]`, `[HH:MM:SS]` - so a retrieved passage can say where it came
from without a second field anywhere.
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
DOCX_EXTS = {".docx"}
PPTX_EXTS = {".pptx"}
XLSX_EXTS = {".xlsx", ".xlsm"}
VTT_EXTS = {".vtt", ".srt"}
# A sheet beyond this is cut and the cut is declared, like a long PDF.
MAX_SHEET_ROWS = 2000
# Transcript cues are grouped into passages of about this many seconds, each headed by its timestamp.
VTT_GROUP_SECONDS = 120
# Formats people will certainly try, named so the refusal is useful rather than generic. The legacy
# binary formats stay refused: the libraries that read them are heavy and the files are rare.
KNOWN_UNSUPPORTED = {
    ".doc": "Old .doc files are not read. Save as .docx or PDF.",
    ".xls": "Old .xls files are not read. Save as .xlsx or export CSV.",
    ".ppt": "Old .ppt files are not read. Save as .pptx or PDF.",
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


def _need(module, what):
    """Import lazily, and turn a missing library into a person-readable refusal (pypdf pattern)."""
    try:
        return __import__(module, fromlist=["_"])
    except ImportError as e:
        raise ExtractError("%s reading is not available on this server" % what) from e


def _rows_block(rows):
    return "\n".join(" | ".join(c for c in r).rstrip(" |") for r in rows if any(c.strip() for c in r))


def extract_docx(data, max_chars=MAX_CHARS):
    """Word -> paragraphs under their headings, then tables as `[table N]` blocks."""
    docx = _need("docx", "Word")
    try:
        d = docx.Document(io.BytesIO(data))
    except Exception as e:                         # noqa: BLE001 - python-docx raises a mix of types
        raise ExtractError("That file does not look like a readable Word document") from e
    parts, cur = [], []
    for p in d.paragraphs:
        t = (p.text or "").strip()
        if not t:
            continue
        style = (p.style.name or "") if p.style is not None else ""
        if style.lower().startswith("heading"):
            if cur:
                parts.append("\n".join(cur))
                cur = []
            cur.append("## " + t)
        else:
            cur.append(t)
    if cur:
        parts.append("\n".join(cur))
    for ti, table in enumerate(d.tables, 1):
        rows = [[(c.text or "").strip().replace("\n", " ") for c in r.cells] for r in table.rows]
        block = _rows_block(rows)
        if block:
            parts.append("[table %d]\n%s" % (ti, block))
    if not parts:
        raise ExtractError("No readable text in that Word document")
    return _cap("\n\n".join(parts), max_chars)


def extract_pptx(data, max_chars=MAX_CHARS):
    """PowerPoint -> one `[slide N]` block per slide: title, text frames, tables, speaker notes."""
    pptx = _need("pptx", "PowerPoint")
    try:
        prs = pptx.Presentation(io.BytesIO(data))
    except Exception as e:                         # noqa: BLE001
        raise ExtractError("That file does not look like a readable PowerPoint deck") from e
    parts, total = [], 0
    for i, slide in enumerate(prs.slides, 1):
        total += 1
        bits = []
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False) and shape.text_frame is not None:
                t = "\n".join(p.text for p in shape.text_frame.paragraphs if p.text).strip()
                if t:
                    bits.append(t)
            if getattr(shape, "has_table", False):
                rows = [[(c.text or "").strip() for c in r.cells] for r in shape.table.rows]
                block = _rows_block(rows)
                if block:
                    bits.append(block)
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            n = (slide.notes_slide.notes_text_frame.text or "").strip()
            if n:
                bits.append("Speaker notes: " + n)
        if bits:
            parts.append("[slide %d]\n%s" % (i, "\n\n".join(bits)))
    if not parts:
        raise ExtractError("No readable text in that deck. If every slide is an image, there is no "
                           "text layer to import.")
    text, note = _cap("\n\n".join(parts), max_chars)
    return text, note, total


def extract_xlsx(data, max_chars=MAX_CHARS):
    """Excel -> one `[sheet Name]` block per worksheet, rows as ` | `-joined cells, values not
    formulas. A sheet past MAX_SHEET_ROWS is cut and the cut is written into the text."""
    openpyxl = _need("openpyxl", "Excel")
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as e:                         # noqa: BLE001
        raise ExtractError("That file does not look like a readable Excel workbook") from e
    parts = []
    for ws in wb.worksheets:
        rows, n, cut = [], 0, False
        for row in ws.iter_rows(values_only=True):
            n += 1
            if n > MAX_SHEET_ROWS:
                cut = True
                break
            rows.append(["" if v is None else str(v).strip() for v in row])
        block = _rows_block(rows)
        if not block:
            continue
        if cut:
            block += ("\n[Import note: sheet %r was cut to fit: only the first %d rows were "
                      "imported. Anything past this point is unknown, not absent.]" % (ws.title, MAX_SHEET_ROWS))
        parts.append("[sheet %s]\n%s" % (ws.title, block))
    if not parts:
        raise ExtractError("No readable cells in that workbook")
    return _cap("\n\n".join(parts), max_chars)


_TS_RE = re.compile(r"(\d{1,2}:)?\d{2}:\d{2}[.,]\d{3}\s*-->\s*(\d{1,2}:)?\d{2}:\d{2}[.,]\d{3}")
_TAG_RE = re.compile(r"<[^>]+>")
_SPEAKER_RE = re.compile(r"^<v\s+([^>]+)>")


def _secs(ts):
    ts = ts.strip().replace(",", ".")
    p = ts.split(":")
    if len(p) == 2:
        p = ["0"] + p
    h, m, s = int(p[0]), int(p[1]), float(p[2])
    return h * 3600 + m * 60 + s, "%02d:%02d:%02d" % (h, m, int(s))


def extract_vtt(data, max_chars=MAX_CHARS, group_seconds=VTT_GROUP_SECONDS):
    """WebVTT / SRT -> cue groups of ~group_seconds, each headed `[HH:MM:SS]`; `<v Name>` speaker
    tags become `Name: text`. For a transcript somebody exported by hand; Fathom's own arrive as JSON
    through the connector."""
    text = _decode(data).replace("\r\n", "\n")
    cues, cur_ts, cur_lines = [], None, []
    for line in text.split("\n") + [""]:
        s = line.strip()
        m = _TS_RE.search(s)
        if m:
            if cur_ts is not None and cur_lines:
                cues.append((cur_ts[0], cur_ts[1], " ".join(cur_lines)))
            cur_ts, cur_lines = _secs(m.group(0).split("-->")[0]), []
            continue
        if not s or s == "WEBVTT" or s.isdigit() or s.startswith(("NOTE", "STYLE", "REGION")):
            if not s and cur_ts is not None and cur_lines:
                cues.append((cur_ts[0], cur_ts[1], " ".join(cur_lines)))
                cur_ts, cur_lines = None, []
            continue
        if cur_ts is None:
            continue
        sp = _SPEAKER_RE.match(s)
        body = _TAG_RE.sub("", s).strip()
        if sp and body:
            body = "%s: %s" % (sp.group(1).strip(), body)
        if body:
            cur_lines.append(body)
    if not cues:
        raise ExtractError("No timed cues in that file. Is it really a WebVTT or SRT transcript?")
    parts, grp, start = [], [], None
    for secs, stamp, body in cues:
        if start is None:
            start = (secs, stamp)
        if secs - start[0] >= group_seconds and grp:
            parts.append("[%s]\n%s" % (start[1], "\n".join(grp)))
            grp, start = [], (secs, stamp)
        grp.append(body)
    if grp:
        parts.append("[%s]\n%s" % (start[1], "\n".join(grp)))
    return _cap("\n\n".join(parts), max_chars)


def _cap(text, max_chars):
    """Cut to the ceiling and DECLARE it in the text (the PDF rule, for every format)."""
    if len(text) <= max_chars:
        return text, ""
    over = len(text) - max_chars
    note = "cut to fit: %d characters were not imported" % over
    return (text[:max_chars] + "\n\n[Import note: this file was cut to fit: %d more characters were "
            "NOT imported. Anything past this point is unknown, not absent.]" % over), note


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
    if ext in DOCX_EXTS:
        text, note = extract_docx(data)
        return {"text": text, "note": note, "kind_hint": "reference", "pages": 0, "pages_imported": 0}
    if ext in PPTX_EXTS:
        text, note, slides = extract_pptx(data)
        return {"text": text, "note": note, "kind_hint": "plan", "pages": slides, "pages_imported": slides}
    if ext in XLSX_EXTS:
        text, note = extract_xlsx(data)
        return {"text": text, "note": note, "kind_hint": "plan", "pages": 0, "pages_imported": 0}
    if ext in VTT_EXTS:
        if _looks_binary(data):
            raise ExtractError("That transcript file does not read as text")
        text, note = extract_vtt(data)
        return {"text": text, "note": note, "kind_hint": "meeting", "pages": 0, "pages_imported": 0}
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
    raise ExtractError("%s files are not read. Upload a PDF, Word, PowerPoint, Excel, WebVTT/SRT, "
                       "text, Markdown or CSV file, or paste the text." % (ext.lstrip(".").upper() or "Those"))


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
        if t and not (t.startswith("[") and t.endswith("]")):
            return t[:120]
    return "Untitled"
