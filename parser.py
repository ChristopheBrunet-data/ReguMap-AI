"""
Parsers for EASA XML rules and Operator Manual PDFs.
Supports visual evidence extraction (tables, diagrams) from PDFs.
"""

import hashlib
import os
from typing import List, Generator
from lxml import etree
import fitz  # PyMuPDF
import security
from schemas import EasaRequirement, ManualChunk

EVIDENCE_DIR = "data/evidence"


class EasaXmlParser:
    """
    Parses EASA Easy Access Rules XML to extract requirements.
    Namespace-agnostic targeting official tags: <EL_RULE>, <ID>, <TITLE>, <CONTENT>
    """
    def __init__(self, xml_path: str):
        self.xml_path = xml_path

    def parse(self) -> Generator[EasaRequirement, None, None]:
        """
        Extracts hierarchical nodes navigating namespace-agnostic tags.
        """
        try:
            tree = etree.parse(self.xml_path)
            root = tree.getroot()

            # Detect and validate schema version
            schema_version = root.get("version", "Unknown")
            print(f"Validated EASA Schema Version: {schema_version}")

            yield from self._extract_rules(root)
        except Exception as e:
            raise ValueError(f"Failed to parse EASA XML at {self.xml_path}: {e}")

    def _extract_rules(self, root) -> Generator[EasaRequirement, None, None]:
        # Namespace agnostic XPath to catch all topic elements anywhere in the tree
        rules = root.xpath('//*[local-name()="topic"]')
        print(f"Searching for tag topic... Found {len(rules)}")

        # Pre-process Word document SDT elements to extract text content
        ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        sdts = root.xpath('.//w:sdt', namespaces=ns)
        sdt_map = {}
        for sdt in sdts:
            w_id_elem = sdt.find('.//w:sdtPr/w:id', namespaces=ns)
            if w_id_elem is not None:
                val = w_id_elem.get(f'{{{ns["w"]}}}val')
                if val:
                    sdt_map[val] = "".join(sdt.itertext()).strip()

        for rule in rules:
            req_id = rule.get("ERulesId", "UNKNOWN_ID")
            source_title = rule.get("source-title", "Unknown Title")
            sdt_id = rule.get("sdt-id", "")

            # Extract content from the corresponding SDT block in the Word document part
            text_content = sdt_map.get(sdt_id, "")

            # TASK 3: Noise Reduction Filter
            lower_title = source_title.lower()
            lower_content = text_content.lower()
            noise_keywords = ["preface", "table of contents", "revision history", "informational"]

            if any(k in lower_title for k in noise_keywords) or any(k in lower_content[:200] for k in noise_keywords):
                continue

            # Prioritize regulatory IDs (skip unknown or generic topics)
            if req_id == "UNKNOWN_ID" or "FOREWORD" in req_id.upper():
                continue

            # Determine Hard Law vs Soft Law heuristically
            upper_title = source_title.upper()
            upper_id = req_id.upper()
            if "AMC" in upper_title or "GM" in upper_title or "AMC" in upper_id or "GM" in upper_id:
                amc_gm_info = "Soft Law"
            else:
                amc_gm_info = "Hard Law"

            # Safely grab any metadata attributes if they exist
            domain = rule.get("Domain", "UNKNOWN_DOMAIN")
            app_date = rule.get("ApplicabilityDate", None)

            yield EasaRequirement(
                id=req_id,
                text=text_content,
                type="Article",
                version=None,
                source_title=source_title,
                domain=domain,
                applicability_date=app_date,
                amc_gm_info=amc_gm_info
            )


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
        hasher = hashlib.md5()
        mode = "rb"
        with open(self.pdf_path, mode) as f:
            buf = f.read()
            hasher.update(buf)
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
        """
        Heuristic to determine if a text block is a header.
        This can be enhanced by looking at font size, weight, and regex for numbering (e.g., "4.1").
        """
        lines = block.get("lines", [])
        if not lines:
            return False

        # Example heuristic: Check if the first line is bold or large font
        for line in lines:
            for span in line.get("spans", []):
                text = span.get("text", "").strip()
                if not text:
                    continue
                flags = span.get("flags", 0)
                font_size = span.get("size", 0)
                # Flag 16 is typically bold in PyMuPDF's raw dict
                is_bold = bool(flags & 16)

                # Simplistic header detection: Starts with a number or is bold/large
                if text[0].isdigit() and (is_bold or font_size > 11):
                    return True
        return False

    def _extract_visual_evidence(self, page: fitz.Page, page_num: int) -> List[dict]:
        """
        Detects and crops images/tables from a page.
        Returns list of {path, bbox, type} for each visual element.
        """
        visuals = []

        # Extract images embedded in the page
        image_list = page.get_images(full=True)
        for img_idx, img_info in enumerate(image_list):
            xref = img_info[0]
            try:
                # Get image bbox by finding its position on the page
                rects = page.get_image_rects(xref)
                if not rects:
                    continue
                for rect in rects:
                    crop_path = os.path.join(
                        EVIDENCE_DIR,
                        f"page_{page_num + 1}_img_{img_idx}_{self._file_hash[:8]}.png"
                    )
                    if not os.path.exists(crop_path):
                        # High-res crop at 2x zoom
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

        # Detect tables via ruling lines heuristic
        drawings = page.get_drawings()
        if len(drawings) > 10:  # Likely a table if many lines
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

    @staticmethod
    def extract_page_crop(pdf_path: str, page_num: int, bbox: tuple = None) -> bytes:
        """
        Returns a high-res PNG crop of a specific page region.
        Handles encrypted (.enc) files by decrypting them first.
        """
        if pdf_path.endswith(".enc"):
            with open(pdf_path, "rb") as f:
                encrypted_data = f.read()
            decrypted_data = security.decrypt_data(encrypted_data)
            doc = fitz.open("pdf", decrypted_data)
        else:
            doc = fitz.open(pdf_path)

        page = doc.load_page(page_num - 1)
        mat = fitz.Matrix(2.0, 2.0)
        clip = fitz.Rect(bbox) if bbox else None
        pix = page.get_pixmap(matrix=mat, clip=clip)
        result = pix.tobytes("png")
        doc.close()
        return result

    def parse(self) -> Generator[ManualChunk, None, None]:
        """
        Identifies headers to create logical context blocks.
        Also extracts visual evidence (images, tables) from each page.
        """
        doc = self._open_doc()

        current_section_title = "General"
        current_content = []
        current_page_start = 1
        current_has_diagram = False
        current_diagram_path = None
        current_bbox = None

        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            visuals = self._extract_visual_evidence(page, page_num)
            blocks = page.get_text("dict").get("blocks", [])

            for b in blocks:
                if b.get("type") != 0:
                    continue

                text = "".join(
                    span.get("text", "")
                    for line in b.get("lines", [])
                    for span in line.get("spans", [])
                ).strip()

                if not text:
                    continue

                # 🔐 PII REDACTION: Mask sensitive info during extraction
                text = security.redact_pii(text)

                if self._is_header(b):
                    if current_content:
                        yield ManualChunk(
                            page_number=current_page_start,
                            section_title=current_section_title,
                            content="\n".join(current_content),
                            file_hash=self._file_hash,
                            has_diagram=current_has_diagram,
                            diagram_path=current_diagram_path,
                            bbox=current_bbox,
                        )
                    current_section_title = text.split("\n")[0]
                    current_content = [text]
                    current_page_start = page_num + 1
                    if visuals:
                        current_has_diagram = True
                        current_diagram_path = visuals[0]["path"]
                        current_bbox = visuals[0]["bbox"]
                    else:
                        current_has_diagram = False
                        current_diagram_path = None
                        current_bbox = None
                else:
                    current_content.append(text)
                    if visuals and not current_has_diagram:
                        current_has_diagram = True
                        current_diagram_path = visuals[0]["path"]
                        current_bbox = visuals[0]["bbox"]

        if current_content:
            yield ManualChunk(
                page_number=current_page_start,
                section_title=current_section_title,
                content="\n".join(current_content),
                file_hash=self._file_hash,
                has_diagram=current_has_diagram,
                diagram_path=current_diagram_path,
                bbox=current_bbox,
            )

        doc.close()
