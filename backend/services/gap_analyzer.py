"""
Gap Analyzer — Event-driven regulatory impact assessment (Task 14).

Subscribes to GRAPH_CHANGED events via the EventBus.
When rules change, cross-references them against existing ManualSections
to identify compliance gaps requiring re-audit.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.event_bus import Event, EventType, get_event_bus

logger = logging.getLogger(__name__)


@dataclass
class GapFinding:
    """A single gap identified between a changed rule and an operator manual section."""
    rule_id: str
    section_id: str
    section_label: str
    change_type: str  # "added", "modified", "removed"
    severity: str     # "critical", "major", "minor"
    description: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class GapAnalysisReport:
    """Complete gap analysis report for a graph change event."""
    trigger_event_id: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    findings: List[GapFinding] = field(default_factory=list)
    rules_analyzed: int = 0
    manual_sections_impacted: int = 0

    @property
    def has_critical(self) -> bool:
        return any(f.severity == "critical" for f in self.findings)

    def summary(self) -> str:
        by_severity = {}
        for f in self.findings:
            by_severity[f.severity] = by_severity.get(f.severity, 0) + 1
        return (
            f"{len(self.findings)} gaps found "
            f"({', '.join(f'{v} {k}' for k, v in by_severity.items())}), "
            f"{self.manual_sections_impacted} manual sections impacted"
        )


class GapAnalyzer:
    """
    Event-driven gap analysis engine.

    Architecture:
    1. Subscribes to GRAPH_CHANGED events
    2. Cross-references changed rules against ManualSection nodes in Neo4j
    3. Generates GapFinding objects for each impacted manual section
    4. Emits GAP_DETECTED events for downstream consumption
    """

    def __init__(self, neo4j_driver: Any = None, knowledge_graph: Any = None):
        self.neo4j_driver = neo4j_driver
        self.knowledge_graph = knowledge_graph
        self.bus = get_event_bus()
        self._reports: List[GapAnalysisReport] = []

        # Auto-subscribe to events (Task 13)
        self.bus.subscribe(EventType.GRAPH_CHANGED, self._on_graph_changed)
        logger.info("GapAnalyzer subscribed to GRAPH_CHANGED events")

    async def _on_graph_changed(self, event: Event) -> None:
        """Event handler: triggered when the regulatory graph changes."""
        logger.info(f"GapAnalyzer triggered by: {event}")
        added = event.data.get("added", [])
        modified = event.data.get("modified", [])
        removed = event.data.get("removed", [])

        report = await self.analyze(
            added_rules=added,
            modified_rules=modified,
            removed_rules=removed,
            trigger_id=event.timestamp,
        )

        if report.findings:
            await self.bus.publish(Event(
                event_type=EventType.GAP_DETECTED,
                source="gap_analyzer",
                data={
                    "summary": report.summary(),
                    "critical": report.has_critical,
                    "findings_count": len(report.findings),
                    "impacted_sections": report.manual_sections_impacted,
                },
            ))

    async def analyze(
        self,
        added_rules: List[str],
        modified_rules: List[str],
        removed_rules: List[str],
        trigger_id: str = "",
    ) -> GapAnalysisReport:
        """
        Run gap analysis for the given set of rule changes.
        Returns a GapAnalysisReport with all findings.
        """
        report = GapAnalysisReport(
            trigger_event_id=trigger_id,
            rules_analyzed=len(added_rules) + len(modified_rules) + len(removed_rules),
        )

        all_changed = added_rules + modified_rules + removed_rules
        impacted_sections = set()

        # 1. Check Neo4j for impacted manual sections
        if self.neo4j_driver and all_changed:
            try:
                from graph.query_engine import find_impacted_manuals
                impacts = find_impacted_manuals(self.neo4j_driver, all_changed)

                for impact in impacts:
                    rule_id = impact["rule_id"]
                    section_id = impact.get("section_id", "unknown")
                    impacted_sections.add(section_id)

                    change_type = (
                        "added" if rule_id in added_rules
                        else "modified" if rule_id in modified_rules
                        else "removed"
                    )

                    severity = "critical" if change_type == "removed" else "major"

                    report.findings.append(GapFinding(
                        rule_id=rule_id,
                        section_id=section_id,
                        section_label=impact.get("section_label", ""),
                        change_type=change_type,
                        severity=severity,
                        description=(
                            f"Rule {rule_id} was {change_type}. "
                            f"Manual section '{impact.get('section_label', section_id)}' "
                            f"(page {impact.get('page_number', '?')}) references this rule "
                            f"and requires compliance re-assessment."
                        ),
                    ))
            except Exception as e:
                logger.error(f"Neo4j impact query failed: {e}")

        # 2. Check NetworkX graph for additional impacts (fallback when Neo4j unavailable)
        if self.knowledge_graph and not impacted_sections:
            try:
                graph = self.knowledge_graph.graph
                for rule_id in all_changed:
                    if graph.has_node(rule_id):
                        # Find nodes linked via MANDATES edges
                        for _, target, data in graph.out_edges(rule_id, data=True):
                            if data.get("edge_type") == "MANDATES":
                                section_id = target
                                impacted_sections.add(section_id)
                                node_data = graph.nodes.get(target, {})

                                change_type = (
                                    "added" if rule_id in added_rules
                                    else "modified" if rule_id in modified_rules
                                    else "removed"
                                )

                                report.findings.append(GapFinding(
                                    rule_id=rule_id,
                                    section_id=section_id,
                                    section_label=node_data.get("label", ""),
                                    change_type=change_type,
                                    severity="major",
                                    description=(
                                        f"Rule {rule_id} was {change_type}. "
                                        f"Manual section '{node_data.get('label', section_id)}' "
                                        f"requires compliance re-assessment (NetworkX fallback)."
                                    ),
                                ))
            except Exception as e:
                logger.error(f"NetworkX impact analysis failed: {e}")

        # 3. For modified rules without existing manual links, flag as informational
        for rule_id in modified_rules:
            if not any(f.rule_id == rule_id for f in report.findings):
                report.findings.append(GapFinding(
                    rule_id=rule_id,
                    section_id="N/A",
                    section_label="No linked manual section",
                    change_type="modified",
                    severity="minor",
                    description=(
                        f"Rule {rule_id} was modified but has no linked manual sections. "
                        f"Review for potential new compliance requirements."
                    ),
                ))

        report.manual_sections_impacted = len(impacted_sections)
        self._reports.append(report)

        logger.info(f"Gap analysis complete: {report.summary()}")
        return report

    def get_reports(self, limit: int = 10) -> List[GapAnalysisReport]:
        """Returns the most recent gap analysis reports."""
        return self._reports[-limit:]

    def get_latest_report(self) -> Optional[GapAnalysisReport]:
        """Returns the most recent report or None."""
        return self._reports[-1] if self._reports else None
