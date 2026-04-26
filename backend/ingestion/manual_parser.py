"""
ManualPdfParser — Extracts chunks from operator manuals (PDF) with visual evidence support.
Implements the sliding window context preservation strategy for high-integrity compliance auditing.
"""

import hashlib
import os
import fitz  # PyMuPDF
from typing import List, Generator
import sys

# Ensure the backend root is in the path to allow absolute imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from schemas import ManualChunk
import security

EVIDENCE_DIR = "data/evidence"

class ManualPdfParser:
    """
    Parses Airline Operator Manuals (PDF) with visual evidence extraction.
    Detects headers, tables, and diagrams. Crops visual elements for traceability.
    """
    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
        self._file_hash = self._compute_hash()
        os.makedirs(EVIDENCE_DIR, exist_ok=True)
        self._is_encrypted = self.pdf_path.endswith(".enc")

    def _compute_hash(self) -> str:
        """Computes a SHA-256 hash of the source PDF for version fingerprinting."""
        hasher = hashlib.sha256()
        with open(self.pdf_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def _open_doc(self) -> fitz.Document:
        """Opens the PDF document, decrypting it into memory if necessary."""
        if self._is_encrypted:
            with open(self.pdf_path, "rb") as f:
                encrypted_data = f.read()
            decrypted_data = security.decrypt_data(encrypted_data)
            return fitz.open("pdf", decrypted_data)
        return fitz.open(self.pdf_path)

    def _is_header(self, block: dict) -> bool:
        """Heuristic to determine if a text block is a header."""
        lines = block.get("lines", [])
        if not lines:
            return False

        for line in lines:
            for span in line.get("spans", []):
                text = span.get("text", "").strip()
                if not text:
                    continue
                flags = span.get("flags", 0)
                font_size = span.get("size", 0)
                is_bold = bool(flags & 16)

                if text[0].isdigit() and (is_bold or font_size > 11):
                    return True
        return False

    def _extract_visual_evidence(self, page: fitz.Page, page_num: int) -> List[dict]:
        """Detects and crops images/tables from a page."""
        visuals = []
        image_list = page.get_images(full=True)
        for img_idx, img_info in enumerate(image_list):
            xref = img_info[0]
            try:
                rects = page.get_image_rects(xref)
                if not rects:
                    continue
                for rect in rects:
                    crop_path = os.path.join(
                        EVIDENCE_DIR,
                        f"page_{page_num + 1}_img_{img_idx}_{self._file_hash[:8]}.png"
                    )
                    if not os.path.exists(crop_path):
                        mat = fitz.Matrix(2.0, 2.0)
                        clip = fitz.Rect(rect)
                        pix = page.get_pixmap(matrix=mat, clip=clip)
                        pix.save(crop_path)
                    visuals.append({
                        "path": crop_path,
                        "bbox": (rect.x0, rect.y0, rect.x1, rect.y1),
                        "type": "image",
                    })
            except Exception:
                continue

        # Detect tables
        drawings = page.get_drawings()
        if len(drawings) > 10:
            crop_path = os.path.join(
                EVIDENCE_DIR,
                f"page_{page_num + 1}_table_{self._file_hash[:8]}.png"
            )
            if not os.path.exists(crop_path):
                mat = fitz.Matrix(2.0, 2.0)
                pix = page.get_pixmap(matrix=mat)
                pix.save(crop_path)
            visuals.append({
                "path": crop_path,
                "bbox": (0, 0, page.rect.width, page.rect.height),
                "type": "table",
            })
        return visuals

    def parse(self, chunk_size: int = 500, overlap: int = 100) -> Generator[ManualChunk, None, None]:
        """Identifies headers and applies a sliding window for context preservation."""
        doc = self._open_doc()
        current_section_title = "General"
        section_content = []
        section_page_start = 1
        section_visuals = []

        def create_chunks(content_list, title, page_num, visuals) -> List[ManualChunk]:
            full_text = "\n".join(content_list)
            words = full_text.split()
            if not words:
                return []
            if len(words) <= chunk_size:
                return [ManualChunk(
                    page_number=page_num,
                    section_title=title,
                    content=full_text,
                    file_hash=self._file_hash,
                    has_diagram=len(visuals) > 0,
                    diagram_path=visuals[0]["path"] if visuals else None,
                    bbox=visuals[0]["bbox"] if visuals else None,
                )]

            chunks = []
            step = chunk_size - overlap
            for i in range(0, len(words), step):
                chunk_words = words[i : i + chunk_size]
                if not chunk_words: break
                chunks.append(ManualChunk(
                    page_number=page_num,
                    section_title=title,
                    content=" ".join(chunk_words),
                    file_hash=self._file_hash,
                    has_diagram=len(visuals) > 0,
                    diagram_path=visuals[0]["path"] if visuals else None,
                    bbox=visuals[0]["bbox"] if visuals else None,
                ))
                if i + chunk_size >= len(words): break
            return chunks

        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            visuals = self._extract_visual_evidence(page, page_num)
            blocks = page.get_text("dict").get("blocks", [])

            for b in blocks:
                if b.get("type") != 0: continue
                text = "".join(s.get("text", "") for l in b.get("lines", []) for s in l.get("spans", [])).strip()
                if not text: continue

                # PII REDACTION
                text = security.redact_pii(text)

                if self._is_header(b):
                    if section_content:
                        yield from create_chunks(section_content, current_section_title, section_page_start, section_visuals)
                    current_section_title = text.split("\n")[0]
                    section_content = [text]
                    section_page_start = page_num + 1
                    section_visuals = visuals
                else:
                    section_content.append(text)
                    if visuals and not section_visuals:
                        section_visuals = visuals

        if section_content:
            yield from create_chunks(section_content, current_section_title, section_page_start, section_visuals)
        doc.close()
