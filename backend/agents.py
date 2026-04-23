"""
Agentic Compliance Board — 4-agent pipeline with multimodal + self-correction.

Agents:
  1. ResearcherAgent   — Discovers rules via hybrid search, re-rank gate at 0.85
  2. ConflictDetector  — Cross-agency conflict analysis (EASA/FAA/DGAC)
  3. AuditorAgent      — Gap analysis with multimodal evidence (diagrams/tables)
  4. CriticAgent       — Self-correcting back-link verification against PDF source
"""

import json
import os
import re
import time
import base64
import security
from typing import List, Optional, Dict
from pydantic import BaseModel, Field
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage
from tenacity import retry, wait_exponential, stop_after_attempt

from schemas import EasaRequirement, ManualChunk, ComplianceAudit, AuditStatus
from knowledge_graph import RegulatoryKnowledgeGraph

# Re-ranker threshold: below this, flag as Noise/Informational
RERANK_THRESHOLD = 0.6

# Known cross-agency reference data for conflict detection
CROSS_AGENCY_REFS = {
    "contingency_fuel": {
        "EASA": "CAT.OP.MPA.150 — 5% of planned trip fuel or 3% with ERA method",
        "FAA": "14 CFR Part-121.645 — 10% of total fuel required for domestic ops",
        "DGAC": "OPS 1.255 — Aligns with EASA but national derogations may apply",
    },
    "flight_time_limitations": {
        "EASA": "ORO.FTL.210 — Max 13h FDP, 900h annual, 1000h calendar year",
        "FAA": "14 CFR Part-117 — Max 9-14h FDP depending on start time, 1000h annual",
        "DGAC": "Arrêté FTL — Follows EASA ORO.FTL with French derogations",
    },
    "crew_training": {
        "EASA": "ORO.FC.230 — Recurrent training every 12 months",
        "FAA": "14 CFR Part-121.427 — Recurrent training with check every 12 months",
        "DGAC": "Follows EASA with supplementary CRIS requirements",
    },
    "maintenance_intervals": {
        "EASA": "Part-M, M.A.302 — AMP based on TC holder's MRB/MPD",
        "FAA": "14 CFR Part-43/91.409 — Progressive or annual inspections",
        "DGAC": "Follows EASA Part-M for EU registered aircraft",
    },
}

# ──────────────────────────────────────────────────────────────────────────────
# 1. Structured Output Models
# ──────────────────────────────────────────────────────────────────────────────

class CrossDomainLink(BaseModel):
    source: str = Field(..., alias="from")
    target: str = Field(..., alias="to")
    relationship: str

class ResearchResult(BaseModel):
    primary_rules: List[str]
    noise_rules: List[str]
    core_topic: str
    cross_domain_links: List[CrossDomainLink]
    regulatory_brief: str
    coverage_gaps: List[str]

class AgencyAnalysis(BaseModel):
    agency: str
    rule_ref: str
    requirement_summary: str
    differs_from_easa: bool
    difference_detail: str

class ConflictDetail(BaseModel):
    rule_a: str
    rule_b: str
    type: str = Field(..., description="CONFLICT|OVERLAP|SUPERSEDED")
    description: str
    severity: str = Field(..., description="HIGH|MEDIUM|LOW")

class ConflictResult(BaseModel):
    core_topic: str
    cross_agency_analysis: List[AgencyAnalysis]
    conflicts: List[ConflictDetail]
    summary: str

class AuditResult(BaseModel):
    requirement_id: str
    status: AuditStatus
    evidence_quote: str
    source_reference: str
    confidence_score: float
    suggested_fix: Optional[str] = None
    cross_refs_used: List[str]
    visual_evidence_pages: List[int]

class CriticResult(BaseModel):
    validation_score: float
    evidence_verified: bool
    citation_verified: bool
    status_justified: bool
    correct_citation: Optional[str] = None
    critique: str
    suggested_fix_valid: Optional[bool] = None

# ──────────────────────────────────────────────────────────────────────────────
# Agent Base
# ──────────────────────────────────────────────────────────────────────────────

class BaseAgent:
    """Shared LLM call logic for all agents."""

    def __init__(self, llm: ChatGoogleGenerativeAI, name: str):
        self.llm = llm
        self.name = name

    @retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(5))
    def _call_structured(self, prompt: ChatPromptTemplate, args: dict, output_schema: type) -> BaseModel:
        print(f"DEBUG: [{self.name}] Calling Gemini for structured output...")
        structured_llm = self.llm.with_structured_output(output_schema)
        chain = prompt | structured_llm
        try:
            response = chain.invoke(args)
            print(f"DEBUG: [{self.name}] Gemini response received.")
            time.sleep(0.5)
            return response
        except Exception as e:
            print(f"DEBUG: [{self.name}] Gemini call failed: {e}")
            raise


# ──────────────────────────────────────────────────────────────────────────────
# 1. Researcher Agent — with re-ranker noise gate
# ──────────────────────────────────────────────────────────────────────────────

class ResearcherAgent(BaseAgent):
    PROMPT = ChatPromptTemplate.from_messages([
        ("system", """You are a Regulatory Researcher specializing in EASA aviation law.
Analyze retrieved rules to build a comprehensive regulatory brief.

Given the user's query, retrieved rules, and their re-ranker scores:
1. Identify PRIMARY rules (re-rank score >= 0.6) that directly address the query.
2. Flag rules with score < 0.6 as 'Noise/Informational' — these should NOT trigger a full audit.
3. Detect CROSS-DOMAIN connections (e.g., Air Ops rule referencing Aircrew requirements).
4. Classify each rule as Hard Law (IR) or Soft Law (AMC/GM).
5. Identify the CORE REGULATORY TOPIC (e.g., 'Contingency Fuel', 'Crew Training').

Return ONLY valid JSON:
{{
    "primary_rules": ["<rule_id>", ...],
    "noise_rules": ["<rule_id>", ...],
    "core_topic": "<The main regulatory topic identified>",
    "cross_domain_links": [
        {{"from": "<rule_id>", "to": "<rule_id>", "relationship": "<description>"}}
    ],
    "regulatory_brief": "<2-3 sentence summary>",
    "coverage_gaps": ["<areas not covered>"]
}}"""),
        ("user", """Query: {query}

Retrieved Rules (with re-ranker scores):
{rules_context}

Graph Context (multi-hop):
{graph_context}""")
    ])

    def research(self, query: str, rules_with_scores: List[tuple], graph_context: str) -> ResearchResult:
        print(f"DEBUG: ResearcherAgent received {len(rules_with_scores)} rules.")
        for r, s in rules_with_scores:
            print(f"  - Rule {r.id}: rerank_score={s:.4f}")

        rules_context = "\n\n---\n\n".join(
            f"[{r.id} | {r.domain} | {r.amc_gm_info} | rerank_score={s:.3f}]\n{r.source_title}\n{r.text[:500]}"
            for r, s in rules_with_scores
        )
        try:
            return self._call_structured(self.PROMPT, {
                "query": query,
                "rules_context": rules_context,
                "graph_context": graph_context,
            }, ResearchResult)
        except Exception as e:
            print(f"Error in ResearcherAgent: {e}")
            return ResearchResult(
                primary_rules=[r.id for r, s in rules_with_scores if s >= RERANK_THRESHOLD],
                noise_rules=[r.id for r, s in rules_with_scores if s < RERANK_THRESHOLD],
                core_topic="General",
                cross_domain_links=[],
                regulatory_brief=f"Research agent encountered an error: {e}",
                coverage_gaps=[]
            )


# ──────────────────────────────────────────────────────────────────────────────
# 2. Conflict Detector — Cross-agency (EASA/FAA/DGAC)
# ──────────────────────────────────────────────────────────────────────────────

class ConflictDetectorAgent(BaseAgent):
    PROMPT = ChatPromptTemplate.from_messages([
        ("system", """You are a Multi-Agency Regulatory Conflict Analyst for aviation safety.
You examine rules across EASA, FAA (14 CFR), and DGAC to find conflicts, contradictions, or ambiguities.

Your process:
1. Identify the CORE REQUIREMENT topic (e.g., Contingency Fuel, Crew Training).
2. Compare the EASA rule against known FAA and DGAC equivalents provided.
3. Flag DIRECT CONFLICTS (contradictory values/thresholds), OVERLAP AMBIGUITIES, and SUPERSEDED rules.
4. Assess severity: HIGH = safety-critical difference, MEDIUM = procedural difference, LOW = editorial.

Return ONLY valid JSON:
{{
    "core_topic": "<e.g., Contingency Fuel>",
    "cross_agency_analysis": [
        {{
            "agency": "<EASA|FAA|DGAC>",
            "rule_ref": "<reference>",
            "requirement_summary": "<what this agency requires>",
            "differs_from_easa": <true|false>,
            "difference_detail": "<specific difference>"
        }}
    ],
    "conflicts": [
        {{
            "rule_a": "<EASA rule>",
            "rule_b": "<FAA/DGAC ref>",
            "type": "<CONFLICT|OVERLAP|SUPERSEDED>",
            "description": "<Precise conflict description>",
            "severity": "<HIGH|MEDIUM|LOW>"
        }}
    ],
    "summary": "<Overall cross-agency conflict assessment>"
}}"""),
        ("user", """Core Topic: {core_topic}

EASA Rules to analyze:
{rules_context}

Cross-Agency Reference Data:
{cross_agency_data}

Known graph conflicts:
{graph_conflicts}""")
    ])

    def detect(self, rules: List[EasaRequirement], graph_conflicts: List[Dict],
               core_topic: str = "General") -> ConflictResult:
        rules_context = "\n\n---\n\n".join(
            f"[{r.id} | {r.domain} | {r.amc_gm_info}]\n{r.source_title}\n{r.text[:600]}"
            for r in rules
        )
        graph_str = json.dumps(graph_conflicts, indent=2) if graph_conflicts else "None detected."

        # Find matching cross-agency reference data
        topic_key = core_topic.lower().replace(" ", "_")
        cross_agency = CROSS_AGENCY_REFS.get(topic_key, {})
        if not cross_agency:
            # Fuzzy match
            for key, data in CROSS_AGENCY_REFS.items():
                if any(word in topic_key for word in key.split("_")):
                    cross_agency = data
                    break
        cross_agency_str = json.dumps(cross_agency, indent=2) if cross_agency else "No cross-agency data for this topic."

        try:
            return self._call_structured(self.PROMPT, {
                "core_topic": core_topic,
                "rules_context": rules_context,
                "cross_agency_data": cross_agency_str,
                "graph_conflicts": graph_str,
            }, ConflictResult)
        except Exception as e:
            print(f"Error in ConflictDetectorAgent: {e}")
            return ConflictResult(
                core_topic=core_topic,
                cross_agency_analysis=[],
                conflicts=[],
                summary=f"Conflict detection error: {e}"
            )


# ──────────────────────────────────────────────────────────────────────────────
# 3. Auditor Agent — with multimodal evidence awareness
# ──────────────────────────────────────────────────────────────────────────────

class AuditorAgent(BaseAgent):
    PROMPT = ChatPromptTemplate.from_messages([
        ("system", """You are an expert Aviation Compliance Auditor with multimodal capabilities.

You receive:
1. The EASA Requirement (Hard Law or Soft Law).
2. Manual chunks with page/section citations.
3. Research brief and conflict report from upstream agents.
4. Regulatory chain context from the Knowledge Graph.
5. Visual evidence indicators (diagrams/tables detected on manual pages).

Instructions:
- If 'Hard Law': be extremely strict. Every point needs explicit evidence.
- If 'Soft Law' (AMC/GM): allow equivalent procedural evidence.
- Quote evidence VERBATIM — do not paraphrase.
- Cite exact page and section.
- If a diagram or table is flagged, note it in evidence_quote as '[Diagram on Page X]' or '[Table on Page X]'.

Return ONLY valid JSON:
{{
    "requirement_id": "<ID>",
    "status": "<Compliant | Partial | Gap>",
    "evidence_quote": "<Verbatim quote or 'None' if Gap>",
    "source_reference": "<Page X, Section Y.Z>",
    "confidence_score": <0.0-1.0>,
    "suggested_fix": "<Fix if Gap/Partial, else null>",
    "cross_refs_used": ["<rule IDs used>"],
    "visual_evidence_pages": [<page numbers with diagrams/tables used as evidence>]
}}"""),
        ("user", """EASA Requirement ID: {req_id}
Regulatory Context: {law_type}
Requirement Text: {req_text}

Research Brief: {research_brief}
Conflict Report: {conflict_report}

Regulatory Chain (from Knowledge Graph):
{graph_chain}

Manual Evidence:
{manual_context}

Visual Evidence Indicators:
{visual_indicators}""")
    ])

    def audit(self, requirement: EasaRequirement, chunks: List[ManualChunk],
              research_brief: str, conflict_report: str, graph_chain: str) -> AuditResult:
        manual_context = "\n\n---\n\n".join(
            f"[Page {c.page_number} | Section: {c.section_title}]\n{c.content}"
            for c in chunks[:5]
        ) or "No manual evidence found."

        # Build visual indicators from chunk metadata
        visual_parts = []
        for c in chunks[:5]:
            if c.has_diagram:
                visual_parts.append(f"Page {c.page_number}: DIAGRAM/TABLE detected (crop: {c.diagram_path})")
        visual_indicators = "\n".join(visual_parts) if visual_parts else "No visual elements detected."

        try:
            return self._call_structured(self.PROMPT, {
                "req_id": requirement.id,
                "law_type": requirement.amc_gm_info or "Unknown",
                "req_text": requirement.text,
                "research_brief": research_brief,
                "conflict_report": conflict_report,
                "graph_chain": graph_chain,
                "manual_context": manual_context,
                "visual_indicators": visual_indicators,
            }, AuditResult)
        except Exception as e:
            print(f"Error in AuditorAgent: {e}")
            return AuditResult(
                requirement_id=requirement.id,
                status=AuditStatus.REQUIRES_HUMAN_REVIEW,
                evidence_quote=f"Auditor error: {e}",
                source_reference="N/A",
                confidence_score=0.0,
                suggested_fix=None,
                cross_refs_used=[],
                visual_evidence_pages=[]
            )


# ──────────────────────────────────────────────────────────────────────────────
# 4. Critic Agent — Self-correcting with back-link PDF verification
# ──────────────────────────────────────────────────────────────────────────────

class CriticAgent(BaseAgent):
    PROMPT = ChatPromptTemplate.from_messages([
        ("system", """You are a Quality Assurance Critic for aviation compliance audits.
You perform BACK-LINK VERIFICATION: re-reading the original PDF source to validate audit findings.

Process:
1. BACK-LINK CHECK: Locate the exact page and paragraph cited in source_reference.
2. QUOTE VERIFICATION: Does the evidence_quote appear verbatim in the cited section?
3. CONTEXT CHECK: Is the quote used in the correct context (not cherry-picked)?
4. STATUS VALIDATION: Is the compliance determination logically justified?
5. FIX VERIFICATION: If a suggested_fix is provided, is it actionable and correct?

If evidence_quote is NOT found at the cited location:
- Set evidence_verified = false
- Search the FULL manual text for the quote
- If found elsewhere, provide the correct citation in your critique
- If not found at all, validation_score must be ≤ 0.3

Scoring:
- 1.0: Exact match at cited location, status fully justified
- 0.7-0.9: Minor paraphrasing, correct location
- 0.4-0.6: Evidence loosely matches or wrong page
- 0.0-0.3: Evidence fabricated or citation completely wrong

Return ONLY valid JSON:
{{
    "validation_score": <0.0-1.0>,
    "evidence_verified": <true|false>,
    "citation_verified": <true|false>,
    "status_justified": <true|false>,
    "correct_citation": "<If citation was wrong, provide the correct one, else null>",
    "critique": "<Detailed explanation of your back-link verification>",
    "suggested_fix_valid": <true|false|null>
}}"""),
        ("user", """Audit Finding to Verify:
- Requirement ID: {req_id}
- Status: {status}
- Evidence Quote: {evidence_quote}
- Source Reference: {source_reference}
- Confidence: {confidence_score}
- Suggested Fix: {suggested_fix}

FULL Original Manual Text (for back-link verification):
{manual_source_text}""")
    ])

    def validate(self, audit_result: AuditResult, cited_chunks: List[ManualChunk],
                  all_chunks: Optional[List[ManualChunk]] = None) -> CriticResult:
        # Use ALL chunks for back-link verification, not just cited ones
        source_chunks = all_chunks[:10] if all_chunks else cited_chunks[:5]
        manual_source = "\n\n---\n\n".join(
            f"[Page {c.page_number} | {c.section_title}]\n{c.content}"
            for c in source_chunks
        ) or "No source material available."

        try:
            return self._call_structured(self.PROMPT, {
                "req_id": audit_result.requirement_id,
                "status": audit_result.status,
                "evidence_quote": audit_result.evidence_quote,
                "source_reference": audit_result.source_reference,
                "confidence_score": audit_result.confidence_score,
                "suggested_fix": audit_result.suggested_fix or "None",
                "manual_source_text": manual_source,
            }, CriticResult)
        except Exception as e:
            print(f"Error in CriticAgent: {e}")
            return CriticResult(
                validation_score=0.0,
                evidence_verified=False,
                citation_verified=False,
                status_justified=False,
                correct_citation=None,
                critique=f"Critic agent error: {e}",
                suggested_fix_valid=None
            )


# ──────────────────────────────────────────────────────────────────────────────
# Multimodal Vision Analyzer — uses Gemini Vision for diagram/table analysis
# ──────────────────────────────────────────────────────────────────────────────

class VisionAnalyzer:
    """Uses Gemini Vision to analyze diagram/table crops from PDFs."""

    def __init__(self, api_key: str, model_name: str = "gemini-2.5-flash"):
        self.llm = ChatGoogleGenerativeAI(
            model=model_name,
            temperature=0.0,
            google_api_key=api_key,
        )

    @retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3))
    def analyze_image(self, image_path: str, context: str = "") -> str:
        """Sends an image crop to Gemini Vision for structured semantic description."""
        if not os.path.exists(image_path):
            return "Image file not found."

        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")

        message = HumanMessage(content=[
            {"type": "text", "text": f"""Analyze this aviation regulatory document element (table, diagram, or figure).
Provide a Structured Semantic Description:
1. TYPE: Is this a table, flowchart, wiring diagram, formula, or schematic?
2. CONTENT: Describe every data point, column, row, or decision path.
3. REGULATORY RELEVANCE: What regulatory requirement does this support?
4. KEY VALUES: Extract specific numerical limits, thresholds, or formulas.

Context: {context}"""},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_data}"}},
        ])

        response = self.llm.invoke([message])
        time.sleep(0.5)
        return response.content.strip()


# ──────────────────────────────────────────────────────────────────────────────
# Compliance Board — Full Orchestrator
# ──────────────────────────────────────────────────────────────────────────────

class ComplianceBoard:
    """
    Orchestrates the 4-agent pipeline with multimodal + self-correction:
    Researcher (+ noise gate) → Conflict Detector (cross-agency) → Auditor (multimodal) → Critic (back-link)
    """

    def __init__(self, api_key: str, model_name: str = "gemini-2.5-flash"):
        llm = ChatGoogleGenerativeAI(
            model=model_name, temperature=0.0, google_api_key=api_key,
        )
        self.researcher = ResearcherAgent(llm, "Researcher")
        self.conflict_detector = ConflictDetectorAgent(llm, "ConflictDetector")
        self.auditor = AuditorAgent(llm, "Auditor")
        self.critic = CriticAgent(llm, "Critic")
        self.vision = VisionAnalyzer(api_key, model_name=model_name)

    def run_full_audit(
        self,
        requirement: EasaRequirement,
        all_rules_scored: List[tuple],
        manual_chunks: List[ManualChunk],
        all_manual_chunks: Optional[List[ManualChunk]] = None,
        knowledge_graph: Optional[RegulatoryKnowledgeGraph] = None,
        query: str = "Standard Compliance Check",
    ) -> ComplianceAudit:
        trace_parts: List[str] = []

        # ── Stage 1: Research + Noise Gate ────────────────────────────────
        graph_context = "No graph available."
        if knowledge_graph and knowledge_graph.is_built():
            try:
                linked = knowledge_graph.get_linked_rules(requirement.id, depth=2)
                graph_context = "\n".join(
                    f"[{r.id} | {r.domain}] {r.source_title}" for r in linked[:8]
                ) or "No linked rules found."
            except Exception as e:
                trace_parts.append(f"GRAPH: traversal failed — {e}")

        try:
            research_result = self.researcher.research(
                query=query,
                rules_with_scores=all_rules_scored[:10],
                graph_context=graph_context,
            )
        except Exception as e:
            print(f"[SELF-HEAL] Researcher failed for {requirement.id}: {e}")
            research_result = ResearchResult(
                primary_rules=[], noise_rules=[], core_topic="General",
                cross_domain_links=[], regulatory_brief="Research unavailable due to error.",
                coverage_gaps=[]
            )
            trace_parts.append(f"RESEARCHER: FAILED — {type(e).__name__}")

        noise_rules = research_result.noise_rules
        core_topic = research_result.core_topic
        trace_parts.append(
            f"RESEARCHER: topic={core_topic}, primary={len(research_result.primary_rules)}, "
            f"noise={len(noise_rules)}"
        )

        # ── Stage 1: Research + Noise Gate ────────────────────────────────
        # ... (Researcher logic) ...
        is_target_noise = requirement.id in noise_rules
        if is_target_noise:
            trace_parts.append("NOISE_GATE: Requirement flagged as noise, but bypassing for explicit audit.")

        # ── Stage 2: Cross-Agency Conflict Detection ──────────────────────
        graph_conflicts = []
        if knowledge_graph and knowledge_graph.is_built():
            try:
                graph_conflicts = knowledge_graph.find_conflicts(requirement.id)
            except Exception as e:
                trace_parts.append(f"GRAPH_CONFLICT: lookup failed — {e}")

        try:
            conflict_result = self.conflict_detector.detect(
                rules=[requirement] + [r for r, _ in all_rules_scored[:5]],
                graph_conflicts=graph_conflicts,
                core_topic=core_topic,
            )
        except Exception as e:
            print(f"[SELF-HEAL] ConflictDetector failed for {requirement.id}: {e}")
            conflict_result = ConflictResult(
                core_topic=core_topic, cross_agency_analysis=[],
                conflicts=[], summary="Conflict analysis unavailable."
            )
            trace_parts.append(f"CONFLICT_DETECTOR: FAILED — {type(e).__name__}")

        n_conflicts = len(conflict_result.conflicts)
        trace_parts.append(f"CONFLICT_DETECTOR: {n_conflicts} conflict(s) found — {conflict_result.summary}")

        # ── Stage 2.5: Multimodal Vision (if diagrams present) ────────────
        visual_description = ""
        evidence_crop_path = None
        for chunk in manual_chunks[:5]:
            if chunk.has_diagram and chunk.diagram_path and os.path.exists(chunk.diagram_path):
                evidence_crop_path = chunk.diagram_path
                try:
                    desc = self.vision.analyze_image(
                        chunk.diagram_path,
                        context=f"Requirement: {requirement.id} — {requirement.source_title}"
                    )
                    visual_description = f"[Visual on Page {chunk.page_number}]: {desc}"
                    trace_parts.append(f"VISION: Analyzed diagram on page {chunk.page_number}")
                except Exception as e:
                    trace_parts.append(f"VISION: Failed — {e}")
                break  # Only analyze first visual

        # ── Stage 3: Audit ────────────────────────────────────────────────
        # Inject visual description into research brief
        research_brief = research_result.regulatory_brief
        if visual_description:
            research_brief += f"\n\nMultimodal Evidence:\n{visual_description}"

        # 🔐 PII REDACTION: Redact briefs and chunks before final audit
        research_brief = security.redact_pii(research_brief)

        try:
            audit_result = self.auditor.audit(
                requirement=requirement,
                chunks=manual_chunks,
                research_brief=research_brief,
                conflict_report=conflict_result.summary,
                graph_chain=graph_context,
            )
        except Exception as e:
            print(f"[SELF-HEAL] Auditor failed for {requirement.id}: {e}")
            audit_result = AuditResult(
                requirement_id=requirement.id,
                status=AuditStatus.REQUIRES_HUMAN_REVIEW,
                evidence_quote="Audit agent encountered an error.",
                source_reference="N/A",
                confidence_score=0.0,
                suggested_fix=f"Manual review required. Auditor error: {str(e)[:150]}",
                cross_refs_used=[],
                visual_evidence_pages=[]
            )
            trace_parts.append(f"AUDITOR: FAILED — {type(e).__name__}")

        # 🔐 OUTPUT SANITIZATION: Check audit output
        quote = audit_result.evidence_quote
        if "ignore" in quote.lower() or "system prompt" in quote.lower():
            audit_result.evidence_quote = "[🛡️ Redacted by Guardrail]"

        trace_parts.append(
            f"AUDITOR: status={audit_result.status}, "
            f"confidence={audit_result.confidence_score}"
        )

        # ── Stage 4: Critic — Back-link self-correction ───────────────────
        try:
            critic_result = self.critic.validate(
                audit_result=audit_result,
                cited_chunks=manual_chunks[:3],
                all_chunks=all_manual_chunks,
            )
        except Exception as e:
            print(f"[SELF-HEAL] Critic failed for {requirement.id}: {e}")
            critic_result = CriticResult(
                validation_score=0.0,
                evidence_verified=False,
                citation_verified=False,
                status_justified=False,
                correct_citation=None,
                critique=f"Critic agent error: {e}",
                suggested_fix_valid=None,
            )
            trace_parts.append(f"CRITIC: FAILED — {type(e).__name__}")

        validation_score = critic_result.validation_score
        correct_citation = critic_result.correct_citation

        # Self-correction: if Critic found wrong citation, fix it
        if correct_citation and not critic_result.citation_verified:
            audit_result.source_reference = correct_citation
            trace_parts.append(f"CRITIC: SELF-CORRECTED citation to '{correct_citation}'")
        else:
            trace_parts.append(
                f"CRITIC: validation={validation_score:.2f}, "
                f"evidence_ok={critic_result.evidence_verified}, "
                f"citation_ok={critic_result.citation_verified}"
            )

        # ── Assemble final result ─────────────────────────────────────────
        final_status = audit_result.status
        confidence = audit_result.confidence_score

        if confidence < 0.6 or validation_score < 0.6:
            final_status = AuditStatus.REQUIRES_HUMAN_REVIEW

        return ComplianceAudit(
            requirement_id=audit_result.requirement_id,
            status=final_status,
            evidence_quote=audit_result.evidence_quote,
            source_reference=audit_result.source_reference,
            confidence_score=confidence,
            suggested_fix=audit_result.suggested_fix,
            cross_refs_used=audit_result.cross_refs_used,
            validation_score=validation_score,
            evidence_crop_path=evidence_crop_path,
            agent_trace=" → ".join(trace_parts),
        )
