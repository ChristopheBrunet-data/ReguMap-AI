"""
S1000D Markdown Converter — Transforms S1000D XML content elements into clean
Markdown with evidence coordinates preserved.

Handles: procedural steps (nested), warnings, cautions, notes, DM references,
figure references, and support equipment lists.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple
from lxml import etree


def element_text(el: etree._Element) -> str:
    """Extract all text content from an element and its children, stripped."""
    return "".join(el.itertext()).strip()


def convert_warning(el: etree._Element) -> str:
    """Convert a <warning> element to Markdown blockquote."""
    para = el.find(".//warningAndCautionPara")
    text = element_text(para) if para is not None else element_text(el)
    return f"> ⚠️ **WARNING**: {text}"


def convert_caution(el: etree._Element) -> str:
    """Convert a <caution> element to Markdown blockquote."""
    para = el.find(".//warningAndCautionPara")
    text = element_text(para) if para is not None else element_text(el)
    return f"> ⚡ **CAUTION**: {text}"


def convert_note(el: etree._Element) -> str:
    """Convert a <note> element to Markdown blockquote."""
    para = el.find(".//notePara")
    text = element_text(para) if para is not None else element_text(el)
    return f"> 📝 **NOTE**: {text}"


def convert_figure(el: etree._Element) -> Tuple[str, Optional[str]]:
    """
    Convert a <figure> element to Markdown image reference.
    Returns (markdown_text, figure_id).
    """
    title_el = el.find("title")
    title = element_text(title_el) if title_el is not None else "Figure"
    graphic = el.find(".//graphic")
    fig_id = graphic.get("infoEntityIdent", "unknown") if graphic is not None else "unknown"
    md = f"![{title}]({fig_id})"
    return md, fig_id


def convert_dm_ref(el: etree._Element) -> Tuple[str, Optional[str]]:
    """
    Convert a <dmRef> element to a Markdown link and extract DMC.
    Returns (markdown_text, dmc_string).
    """
    dm_code = el.find(".//dmCode")
    title_el = el.find(".//dmTitle")

    dmc = _build_dmc_from_element(dm_code) if dm_code is not None else "unknown"

    tech_name = ""
    info_name = ""
    if title_el is not None:
        tn = title_el.find("techName")
        inn = title_el.find("infoName")
        tech_name = element_text(tn) if tn is not None else ""
        info_name = element_text(inn) if inn is not None else ""

    display = f"{tech_name} — {info_name}".strip(" —") if tech_name else dmc
    md = f"[{display}](dmc:{dmc})"
    return md, dmc


def _build_dmc_from_element(dm_code: etree._Element) -> str:
    """Build a DMC string from a <dmCode> element's attributes."""
    parts = [
        dm_code.get("modelIdentCode", ""),
        dm_code.get("systemCode", ""),
        dm_code.get("subSystemCode", ""),
        dm_code.get("subSubSystemCode", ""),
        dm_code.get("assyCode", ""),
        dm_code.get("disassyCode", ""),
        dm_code.get("disassyCodeVariant", ""),
        dm_code.get("infoCode", ""),
        dm_code.get("infoCodeVariant", ""),
        dm_code.get("itemLocationCode", ""),
    ]
    # Format: MODEL-SYS-SUB-SUBSUB-ASSY-DISASSY+VAR-INFO+VAR-LOC
    if parts[0]:
        return (
            f"{parts[0]}-{parts[1]}-{parts[2]}{parts[3]}-"
            f"{parts[4]}-{parts[5]}{parts[6]}-"
            f"{parts[7]}{parts[8]}-{parts[9]}"
        )
    return "-".join(p for p in parts if p)


def convert_procedural_steps(
    parent: etree._Element,
    depth: int = 0,
    step_prefix: str = "",
    base_path: str = "mainProcedure",
) -> Tuple[List[str], List[str], List[str], List[str]]:
    """
    Recursively convert <proceduralStep> elements to numbered Markdown.

    Returns:
        (lines, warnings, cautions, notes) — collected from the step hierarchy.
    """
    lines: List[str] = []
    warnings: List[str] = []
    cautions: List[str] = []
    notes: List[str] = []
    indent = "  " * depth

    step_elements = parent.findall("proceduralStep")
    for i, step in enumerate(step_elements, 1):
        step_num = f"{step_prefix}{i}" if step_prefix else str(i)
        step_path = f"{base_path}/step[{i}]"

        # Process child elements in document order
        for child in step:
            tag = etree.QName(child).localname if isinstance(child.tag, str) else str(child.tag)

            if tag == "para":
                text = element_text(child)
                if text:
                    lines.append(f"{indent}{step_num}. {text}")

            elif tag == "warning":
                w = convert_warning(child)
                lines.append(f"{indent}{w}")
                warnings.append(element_text(child))

            elif tag == "caution":
                c = convert_caution(child)
                lines.append(f"{indent}{c}")
                cautions.append(element_text(child))

            elif tag == "note":
                n = convert_note(child)
                lines.append(f"{indent}{n}")
                notes.append(element_text(child))

            elif tag == "figure":
                fig_md, _ = convert_figure(child)
                lines.append(f"{indent}{fig_md}")

            elif tag == "proceduralStep":
                # Nested step — recurse (handled below)
                pass

        # Recurse into nested steps
        sub_lines, sub_w, sub_c, sub_n = convert_procedural_steps(
            step, depth=depth + 1, step_prefix=f"{step_num}.",
            base_path=step_path,
        )
        lines.extend(sub_lines)
        warnings.extend(sub_w)
        cautions.extend(sub_c)
        notes.extend(sub_n)

    return lines, warnings, cautions, notes


def convert_preliminary_rqmts(prelim: etree._Element) -> Tuple[List[str], List[str], List[str], List[str], List[str]]:
    """
    Convert <preliminaryRqmts> to Markdown.
    Returns (lines, dm_refs, warnings, cautions, support_equips).
    """
    lines: List[str] = []
    dm_refs: List[str] = []
    all_warnings: List[str] = []
    all_cautions: List[str] = []
    equips: List[str] = []

    # Required conditions (DM references)
    for dm_ref in prelim.findall(".//reqCondDm//dmRef"):
        md, dmc = convert_dm_ref(dm_ref)
        lines.append(f"- **Prerequisite**: {md}")
        if dmc:
            dm_refs.append(dmc)

    # Support equipment
    for equip in prelim.findall(".//supportEquipDescr"):
        name_el = equip.find("name")
        part_el = equip.find(".//partNumber")
        name = element_text(name_el) if name_el is not None else "Unknown"
        part = element_text(part_el) if part_el is not None else ""
        equip_str = f"- **Equipment**: {name}" + (f" (P/N: {part})" if part else "")
        lines.append(equip_str)
        equips.append(name)

    # Safety requirements
    for w in prelim.findall(".//reqSafety//warning"):
        md = convert_warning(w)
        lines.append(md)
        all_warnings.append(element_text(w))

    for c in prelim.findall(".//reqSafety//caution"):
        md = convert_caution(c)
        lines.append(md)
        all_cautions.append(element_text(c))

    return lines, dm_refs, all_warnings, all_cautions, equips


def convert_close_rqmts(close: etree._Element) -> Tuple[List[str], List[str]]:
    """Convert <closeRqmts> to Markdown. Returns (lines, dm_refs)."""
    lines: List[str] = []
    dm_refs: List[str] = []

    for dm_ref in close.findall(".//dmRef"):
        md, dmc = convert_dm_ref(dm_ref)
        lines.append(f"- **Follow-up**: {md}")
        if dmc:
            dm_refs.append(dmc)

    return lines, dm_refs
