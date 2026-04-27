"""
Watchdog Routes — Regulatory surveillance and gap analysis API surface (Task 15).

POST /api/v1/watchdog/scan          — Trigger RSS/crawl scan for updates
GET  /api/v1/watchdog/alerts        — View current regulatory alerts
GET  /api/v1/watchdog/gaps          — View gap analysis reports
POST /api/v1/watchdog/analyze       — Run gap analysis for specific rules
GET  /api/v1/watchdog/events        — View event bus history
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api_pkg.dependencies import get_engine, get_neo4j_driver

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/watchdog", tags=["Watchdog"])


# ──────────────────────────────────────────────────────────────────────────────
# Request/Response Schemas
# ──────────────────────────────────────────────────────────────────────────────

class ScanResponse(BaseModel):
    """Response from a watchdog scan."""
    status: str
    new_updates_found: bool = False
    domains_checked: int = 0
    details: Dict[str, Any] = Field(default_factory=dict)


class AlertResponse(BaseModel):
    """A single regulatory alert."""
    id: str
    title: str
    severity: str
    timestamp: str
    rule_ids: List[str] = Field(default_factory=list)
    description: str = ""


class GapFindingResponse(BaseModel):
    """A single gap finding."""
    rule_id: str
    section_id: str
    section_label: str
    change_type: str
    severity: str
    description: str
    timestamp: str


class GapReportResponse(BaseModel):
    """A gap analysis report."""
    trigger_event_id: str
    timestamp: str
    findings: List[GapFindingResponse]
    rules_analyzed: int
    manual_sections_impacted: int
    summary: str


class AnalyzeRequest(BaseModel):
    """Request body for manual gap analysis."""
    rule_ids: List[str] = Field(..., description="Rule IDs to analyze for gaps")
    change_type: str = Field("modified", description="Type of change: added, modified, removed")


class EventResponse(BaseModel):
    """An event from the event bus."""
    event_type: str
    source: str
    timestamp: str
    data: Dict[str, Any] = Field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────────────────

@router.post(
    "/scan",
    response_model=ScanResponse,
    summary="Trigger regulatory scan",
    description="Checks EASA RSS feeds and domain pages for regulatory updates.",
)
async def trigger_scan():
    """Runs the RSS scanner and returns whether new updates were found."""
    try:
        from crawler import check_for_updates
        found_update = check_for_updates()

        return ScanResponse(
            status="complete",
            new_updates_found=found_update,
            domains_checked=1,  # RSS-based scan covers the feed
            details={"method": "rss_feed"},
        )
    except Exception as e:
        logger.error(f"Watchdog scan failed: {e}")
        raise HTTPException(status_code=500, detail=f"Scan failed: {str(e)}")


@router.get(
    "/alerts",
    response_model=List[AlertResponse],
    summary="View regulatory alerts",
    description="Returns current alerts from the regulatory watchdog.",
)
async def get_alerts(limit: int = Query(20, ge=1, le=100)):
    """Returns regulatory alerts from the event bus history."""
    from services.event_bus import EventType, get_event_bus

    bus = get_event_bus()
    events = bus.get_history(EventType.WATCHDOG_ALERT)
    alerts = []

    for i, event in enumerate(events[-limit:]):
        alerts.append(AlertResponse(
            id=f"alert-{i}",
            title=event.data.get("title", "Regulatory Update"),
            severity=event.data.get("severity", "info"),
            timestamp=event.timestamp,
            rule_ids=event.data.get("rule_ids", []),
            description=event.data.get("description", ""),
        ))

    # Also include GAP_DETECTED events as high-severity alerts
    gap_events = bus.get_history(EventType.GAP_DETECTED)
    for i, event in enumerate(gap_events[-limit:]):
        alerts.append(AlertResponse(
            id=f"gap-alert-{i}",
            title=f"Gap Detected: {event.data.get('findings_count', 0)} findings",
            severity="critical" if event.data.get("critical") else "major",
            timestamp=event.timestamp,
            rule_ids=[],
            description=event.data.get("summary", ""),
        ))

    return sorted(alerts, key=lambda a: a.timestamp, reverse=True)[:limit]


@router.get(
    "/gaps",
    response_model=List[GapReportResponse],
    summary="View gap analysis reports",
    description="Returns recent gap analysis reports.",
)
async def get_gap_reports(limit: int = Query(10, ge=1, le=50)):
    """Returns gap analysis reports from the GapAnalyzer."""
    try:
        from services.gap_analyzer import GapAnalyzer
        # Get the global analyzer if it exists
        from api_pkg.dependencies import get_neo4j_driver, get_engine
        engine = get_engine()
        driver = get_neo4j_driver()
        analyzer = GapAnalyzer(neo4j_driver=driver, knowledge_graph=engine.knowledge_graph)

        reports = analyzer.get_reports(limit=limit)
        return [
            GapReportResponse(
                trigger_event_id=r.trigger_event_id,
                timestamp=r.timestamp,
                findings=[
                    GapFindingResponse(
                        rule_id=f.rule_id,
                        section_id=f.section_id,
                        section_label=f.section_label,
                        change_type=f.change_type,
                        severity=f.severity,
                        description=f.description,
                        timestamp=f.timestamp,
                    )
                    for f in r.findings
                ],
                rules_analyzed=r.rules_analyzed,
                manual_sections_impacted=r.manual_sections_impacted,
                summary=r.summary(),
            )
            for r in reports
        ]
    except Exception as e:
        logger.error(f"Failed to retrieve gap reports: {e}")
        return []


@router.post(
    "/analyze",
    response_model=GapReportResponse,
    summary="Run manual gap analysis",
    description="Manually trigger gap analysis for specific rule IDs.",
)
async def run_manual_analysis(request: AnalyzeRequest):
    """Run gap analysis for explicitly specified rule IDs."""
    try:
        from services.gap_analyzer import GapAnalyzer
        from api_pkg.dependencies import get_neo4j_driver, get_engine

        engine = get_engine()
        driver = get_neo4j_driver()
        analyzer = GapAnalyzer(neo4j_driver=driver, knowledge_graph=engine.knowledge_graph)

        added = request.rule_ids if request.change_type == "added" else []
        modified = request.rule_ids if request.change_type == "modified" else []
        removed = request.rule_ids if request.change_type == "removed" else []

        report = await analyzer.analyze(
            added_rules=added,
            modified_rules=modified,
            removed_rules=removed,
            trigger_id="manual-analysis",
        )

        return GapReportResponse(
            trigger_event_id=report.trigger_event_id,
            timestamp=report.timestamp,
            findings=[
                GapFindingResponse(
                    rule_id=f.rule_id,
                    section_id=f.section_id,
                    section_label=f.section_label,
                    change_type=f.change_type,
                    severity=f.severity,
                    description=f.description,
                    timestamp=f.timestamp,
                )
                for f in report.findings
            ],
            rules_analyzed=report.rules_analyzed,
            manual_sections_impacted=report.manual_sections_impacted,
            summary=report.summary(),
        )
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"Manual gap analysis failed: {e}")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@router.get(
    "/events",
    response_model=List[EventResponse],
    summary="View event bus history",
    description="Returns recent events from the system event bus.",
)
async def get_event_history(
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    limit: int = Query(50, ge=1, le=100),
):
    """Returns recent events from the event bus."""
    from services.event_bus import EventType, get_event_bus

    bus = get_event_bus()

    if event_type:
        try:
            filtered_type = EventType(event_type)
            events = bus.get_history(filtered_type)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown event type: {event_type}. "
                       f"Valid types: {[e.value for e in EventType]}",
            )
    else:
        events = bus.get_history()

    return [
        EventResponse(
            event_type=e.event_type.value,
            source=e.source,
            timestamp=e.timestamp,
            data=e.data,
        )
        for e in events[-limit:]
    ]
