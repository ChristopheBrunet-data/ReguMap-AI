"""
PDF Mapper — Scans EASA PDFs to build Rule ID → Page Number index.
Uses PyMuPDF (fitz) to search for regulatory IDs in each page.
Index is persisted to JSON for instant lookup.
"""

import json
import os
import re
from typing import Dict, Optional, Tuple

import fitz  # PyMuPDF
from core_constants import EASA_RULE_ID_PATTERN

INDEX_DIR = "data/pdf_index"
CROP_DIR = "data/evidence/pdf_crops"


class PdfMapper:
    """
    Scans EASA PDFs and builds a mapping of Rule_ID → {page, bbox, domain, pdf_path}.
    Persisted to JSON so it only needs to run once per PDF.
    """

    def __init__(self):
        self.index: Dict[str, dict] = {}  # rule_id → {page, domain, pdf_path, bbox}
        self.index_path = os.path.join(INDEX_DIR, "rule_page_index.json")
        os.makedirs(INDEX_DIR, exist_ok=True)
        os.makedirs(CROP_DIR, exist_ok=True)

    def load(self) -> bool:
        """Load existing index from disk."""
        if os.path.exists(self.index_path):
            with open(self.index_path, "r", encoding="utf-8") as f:
                self.index = json.load(f)
            print(f"PDF index loaded: {len(self.index)} rule→page mappings.")
            return True
        return False

    def save(self):
        """Persist index to disk."""
        with open(self.index_path, "w", encoding="utf-8") as f:
            json.dump(self.index, f, ensure_ascii=False, indent=1)
        print(f"PDF index saved: {len(self.index)} entries.")

    def scan_pdf(self, pdf_path: str, domain: str):
        """
        Scans a PDF for all EASA rule IDs, recording the first occurrence
        of each rule ID with its page number and bounding box.
        """
        if not os.path.exists(pdf_path):
            print(f"PDF not found: {pdf_path}")
            return

        print(f"Scanning PDF for rule anchors: {pdf_path} ({domain})...")
        doc = fitz.open(pdf_path)
        found_count = 0

        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            text = page.get_text()

            matches = EASA_RULE_ID_PATTERN.findall(text)
            for rule_id in set(matches):
                # Only store the FIRST occurrence of each rule
                if rule_id in self.index:
                    continue

                # Find the exact position on the page for cropping
                text_instances = page.search_for(rule_id)
                bbox = None
                if text_instances:
                    # Take the first instance rect
                    rect = text_instances[0]
                    # Expand bbox to capture surrounding paragraph context
                    bbox = (
                        max(0, rect.x0 - 20),
                        max(0, rect.y0 - 40),
                        min(page.rect.width, rect.x1 + 400),
                        min(page.rect.height, rect.y1 + 120),
                    )

                self.index[rule_id] = {
                    "page": page_num + 1,  # 1-indexed
                    "domain": domain,
                    "pdf_path": pdf_path,
                    "bbox": list(bbox) if bbox else None,
                }
                found_count += 1

        doc.close()
        print(f"  Found {found_count} new rule anchors in {domain}.")

    def scan_all_pdfs(self, pdf_paths: dict):
        """Scans all available domain PDFs and builds the complete index."""
        for domain, pdf_path in pdf_paths.items():
            self.scan_pdf(pdf_path, domain)
        self.save()

    def get_page(self, rule_id: str) -> Optional[int]:
        """Returns the page number for a given rule ID, or None."""
        entry = self.index.get(rule_id)
        return entry["page"] if entry else None

    def get_entry(self, rule_id: str) -> Optional[dict]:
        """Returns full index entry for a rule ID."""
        return self.index.get(rule_id)

    def get_page_crop(self, rule_id: str, zoom: float = 2.0) -> Optional[bytes]:
        """
        Renders a high-res crop of the PDF region where the rule appears.
        Returns PNG bytes or None.
        """
        entry = self.index.get(rule_id)
        if not entry or not entry.get("pdf_path"):
            return None

        pdf_path = entry["pdf_path"]
        if not os.path.exists(pdf_path):
            return None

        page_num = entry["page"] - 1  # 0-indexed for fitz
        bbox = entry.get("bbox")

        try:
            doc = fitz.open(pdf_path)
            page = doc.load_page(page_num)
            mat = fitz.Matrix(zoom, zoom)
            clip = fitz.Rect(bbox) if bbox else None
            pix = page.get_pixmap(matrix=mat, clip=clip)
            result = pix.tobytes("png")
            doc.close()
            return result
        except Exception as e:
            print(f"Failed to crop rule {rule_id}: {e}")
            return None

    def save_crop(self, rule_id: str) -> Optional[str]:
        """
        Saves a crop image for the rule and returns the file path.
        Used for caching crops displayed in the UI.
        """
        safe_id = rule_id.replace(".", "_")
        crop_path = os.path.join(CROP_DIR, f"{safe_id}.png")

        if os.path.exists(crop_path):
            return crop_path

        crop_data = self.get_page_crop(rule_id)
        if crop_data:
            with open(crop_path, "wb") as f:
                f.write(crop_data)
            return crop_path
        return None

    def render_full_page(self, rule_id: str, zoom: float = 1.5) -> Optional[bytes]:
        """Renders the full page where a rule appears as PNG."""
        entry = self.index.get(rule_id)
        if not entry or not entry.get("pdf_path"):
            return None

        pdf_path = entry["pdf_path"]
        if not os.path.exists(pdf_path):
            return None

        try:
            doc = fitz.open(pdf_path)
            page = doc.load_page(entry["page"] - 1)
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)
            result = pix.tobytes("png")
            doc.close()
            return result
        except Exception as e:
            print(f"Failed to render page for {rule_id}: {e}")
            return None

    def get_stats(self) -> dict:
        """Returns index statistics."""
        domains = {}
        for entry in self.index.values():
            d = entry.get("domain", "unknown")
            domains[d] = domains.get(d, 0) + 1
        return {
            "total_mappings": len(self.index),
            "domains": domains,
        }
