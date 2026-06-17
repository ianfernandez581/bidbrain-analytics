"""Build a Google Slides deck from the VMCH payload + rendered chart PNGs.

Auth: Application Default Credentials (your gcloud login) with Drive + Slides
scopes, so the deck is created in *your* Google Drive and owned by you. If ADC
lacks the scopes you'll get a clear error telling you which login command to run
(see report.py / README).

Image flow: Slides' createImage needs a URL it can fetch. We upload each PNG to
Drive, flip it to anyone-with-link-reader, createImage (Slides copies the bytes
into the deck), then delete the temporary Drive file — so nothing public lingers.
"""
from __future__ import annotations

import struct
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# 16:9 slide canvas in EMU (1 inch = 914400 EMU)
EMU_IN = 914400
SLIDE_W = 9144000
SLIDE_H = 5143500
MARGIN = 457200  # 0.5in


def png_size(path: Path) -> tuple[int, int]:
    """(width, height) in px from the PNG header — no PIL dependency."""
    with open(path, "rb") as f:
        head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        return (1000, 520)
    w, h = struct.unpack(">II", head[16:24])
    return (w, h)


def _fit(box_w: int, box_h: int, aspect: float) -> tuple[int, int]:
    """Largest (w,h) EMU with the given aspect that fits inside box."""
    if box_w / box_h > aspect:          # box wider than image -> height-bound
        h = box_h
        w = int(h * aspect)
    else:
        w = box_w
        h = int(w / aspect)
    return w, h


class DeckBuilder:
    def __init__(self, creds):
        self.slides = build("slides", "v1", credentials=creds)
        self.drive = build("drive", "v3", credentials=creds)
        self._tmp_files: list[str] = []

    # --- public ---------------------------------------------------------------
    def build(self, title: str, subtitle: str, kpis: list[tuple[str, str]],
              charts: list[dict], folder_id: str | None = None) -> str:
        """Create the deck, return its URL."""
        pres = self.slides.presentations().create(body={"title": title}).execute()
        pid = pres["presentationId"]
        self._last_pres = pres
        if folder_id:
            self._move_to_folder(pid, folder_id)

        first_slide_id = pres["slides"][0]["objectId"]
        reqs: list[dict] = []
        self._fill_title_slide(reqs, first_slide_id, title, subtitle)
        self._add_kpi_slide(reqs, kpis)
        self.slides.presentations().batchUpdate(
            presentationId=pid, body={"requests": reqs}).execute()

        # Chart slides need the image uploaded first (per-chart batch).
        for ch in charts:
            self._add_chart_slide(pid, ch)

        self._cleanup_tmp()
        return f"https://docs.google.com/presentation/d/{pid}/edit"

    # --- slide builders -------------------------------------------------------
    def _fill_title_slide(self, reqs, slide_id, title, subtitle):
        # The default first slide carries TITLE + SUBTITLE placeholders.
        ph = self._placeholders(slide_id)
        if "TITLE" in ph or "CENTERED_TITLE" in ph:
            tid = ph.get("CENTERED_TITLE") or ph.get("TITLE")
            reqs.append({"insertText": {"objectId": tid, "text": title}})
        if "SUBTITLE" in ph:
            reqs.append({"insertText": {"objectId": ph["SUBTITLE"], "text": subtitle}})

    def _add_kpi_slide(self, reqs, kpis):
        sid = "kpi_slide"
        reqs.append({"createSlide": {"objectId": sid,
                                     "slideLayoutReference": {"predefinedLayout": "BLANK"}}})
        self._title_box(reqs, sid, "Campaign at a glance")
        # 2-column KPI grid of text boxes
        cols, gap = 2, 228600
        col_w = (SLIDE_W - 2 * MARGIN - gap) // cols
        row_h = 685800
        top0 = 1371600
        for i, (label, value) in enumerate(kpis):
            r, c = divmod(i, cols)
            x = MARGIN + c * (col_w + gap)
            y = top0 + r * (row_h + 91440)
            box = f"{sid}_kpi{i}"
            reqs.append({"createShape": {"objectId": box, "shapeType": "TEXT_BOX",
                "elementProperties": {"pageObjectId": sid, "size": _sz(col_w, row_h),
                                      "transform": _xform(x, y)}}})
            reqs.append({"insertText": {"objectId": box, "text": f"{value}\n{label}"}})
            # value line big, label line small/muted
            reqs.append({"updateTextStyle": {"objectId": box,
                "textRange": {"type": "FIXED_RANGE", "startIndex": 0, "endIndex": len(value)},
                "style": {"fontSize": {"magnitude": 30, "unit": "PT"}, "bold": True,
                          "foregroundColor": _color("#2A1E20")},
                "fields": "fontSize,bold,foregroundColor"}})
            reqs.append({"updateTextStyle": {"objectId": box,
                "textRange": {"type": "FIXED_RANGE",
                              "startIndex": len(value) + 1, "endIndex": len(value) + 1 + len(label)},
                "style": {"fontSize": {"magnitude": 12, "unit": "PT"},
                          "foregroundColor": _color("#8C7E80")},
                "fields": "fontSize,foregroundColor"}})

    def _add_chart_slide(self, pid, ch: dict):
        url = self._upload_public_png(ch["path"])
        w_px, h_px = png_size(ch["path"])
        aspect = w_px / h_px
        box_w = SLIDE_W - 2 * MARGIN
        box_h = SLIDE_H - 1280160 - MARGIN     # leave room for the title bar
        img_w, img_h = _fit(box_w, box_h, aspect)
        x = (SLIDE_W - img_w) // 2
        y = 1280160 + ((box_h - img_h) // 2)

        sid = "s_" + ch["key"]
        iid = "i_" + ch["key"]
        reqs = [{"createSlide": {"objectId": sid,
                                 "slideLayoutReference": {"predefinedLayout": "BLANK"}}}]
        self._title_box(reqs, sid, ch["title"])
        reqs.append({"createImage": {"objectId": iid, "url": url,
            "elementProperties": {"pageObjectId": sid, "size": _sz(img_w, img_h),
                                  "transform": _xform(x, y)}}})
        self.slides.presentations().batchUpdate(
            presentationId=pid, body={"requests": reqs}).execute()

    # --- helpers --------------------------------------------------------------
    def _title_box(self, reqs, sid, text):
        box = f"{sid}_title"
        reqs.append({"createShape": {"objectId": box, "shapeType": "TEXT_BOX",
            "elementProperties": {"pageObjectId": sid,
                "size": _sz(SLIDE_W - 2 * MARGIN, 640080),
                "transform": _xform(MARGIN, 411480)}}})
        reqs.append({"insertText": {"objectId": box, "text": text}})
        reqs.append({"updateTextStyle": {"objectId": box,
            "style": {"fontSize": {"magnitude": 22, "unit": "PT"}, "bold": True,
                      "foregroundColor": _color("#4C2736")},
            "fields": "fontSize,bold,foregroundColor"}})

    def _placeholders(self, slide_id) -> dict[str, str]:
        # Map placeholder types -> object ids from the create() response
        # (read before any batch mutates the default slide's layout).
        out: dict[str, str] = {}
        p = self._last_pres
        for s in p.get("slides", []):
            if s["objectId"] != slide_id:
                continue
            for el in s.get("pageElements", []):
                ph = el.get("shape", {}).get("placeholder")
                if ph:
                    out[ph["type"]] = el["objectId"]
        return out

    # --- drive image upload ---------------------------------------------------
    def _upload_public_png(self, path: Path) -> str:
        media = MediaFileUpload(str(path), mimetype="image/png")
        f = self.drive.files().create(
            body={"name": path.name}, media_body=media, fields="id").execute()
        fid = f["id"]
        self._tmp_files.append(fid)
        self.drive.permissions().create(
            fileId=fid, body={"type": "anyone", "role": "reader"}).execute()
        return f"https://drive.google.com/uc?export=view&id={fid}"

    def _move_to_folder(self, file_id, folder_id):
        f = self.drive.files().get(fileId=file_id, fields="parents").execute()
        prev = ",".join(f.get("parents", []))
        self.drive.files().update(fileId=file_id, addParents=folder_id,
                                  removeParents=prev, fields="id").execute()

    def _cleanup_tmp(self):
        for fid in self._tmp_files:
            try:
                self.drive.files().delete(fileId=fid).execute()
            except Exception as e:
                print(f"  warn: could not delete temp drive file {fid}: {e}")
        self._tmp_files.clear()

    # the create() response is stashed so _placeholders can read placeholders
    _last_pres: dict = {}


def _sz(w, h):
    return {"width": {"magnitude": w, "unit": "EMU"},
            "height": {"magnitude": h, "unit": "EMU"}}


def _xform(x, y):
    return {"scaleX": 1, "scaleY": 1, "translateX": x, "translateY": y, "unit": "EMU"}


def _color(hexstr):
    h = hexstr.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return {"opaqueColor": {"rgbColor": {"red": r, "green": g, "blue": b}}}
