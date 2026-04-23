"""
Regulatory Watchdog — monitors EASA RSS feeds for new regulations
and triggers proactive impact analysis against uploaded manuals.

Persists alerts and compliance tasks to JSON.
"""

import json
import os
import re
import time
import datetime
import feedparser
import requests
from typing import List, Optional
from schemas import Alert, ComplianceTask
from core_constants import EASA_RULE_ID_PATTERN

ALERTS_DIR = "data/watchdog"
ALERTS_FILE = os.path.join(ALERTS_DIR, "alerts.json")
TASKS_FILE = os.path.join(ALERTS_DIR, "compliance_tasks.json")

# EASA RSS feed URLs (official + technical publications)
RSS_FEEDS = {
    "easy_access_rules": "https://www.easa.europa.eu/en/document-library/easy-access-rules/feed.xml",
    "agency_decisions": "https://www.easa.europa.eu/en/document-library/agency-decisions/feed.xml",
    "opinions": "https://www.easa.europa.eu/en/document-library/opinions/feed.xml",
    "notices_proposed_amendment": "https://www.easa.europa.eu/en/document-library/notices-of-proposed-amendment/feed.xml",
}

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# Constants and directories


def _init_dirs():
    os.makedirs(ALERTS_DIR, exist_ok=True)


def _load_json(filepath: str) -> list:
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _save_json(filepath: str, data: list):
    _init_dirs()
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


_ALERTS_CACHE: Optional[List[Alert]] = None
_TASKS_CACHE: Optional[List[ComplianceTask]] = None

def _load_alerts() -> List[Alert]:
    global _ALERTS_CACHE
    if _ALERTS_CACHE is None:
        raw_data = _load_json(ALERTS_FILE)
        _ALERTS_CACHE = [Alert(**a) for a in raw_data]
    return _ALERTS_CACHE

def _load_tasks() -> List[ComplianceTask]:
    global _TASKS_CACHE
    if _TASKS_CACHE is None:
        raw_data = _load_json(TASKS_FILE)
        _TASKS_CACHE = [ComplianceTask(**t) for t in raw_data]
    return _TASKS_CACHE

def flush_to_disk():
    global _ALERTS_CACHE, _TASKS_CACHE
    if _ALERTS_CACHE is not None:
        _save_json(ALERTS_FILE, [a.model_dump() for a in _ALERTS_CACHE])
    if _TASKS_CACHE is not None:
        _save_json(TASKS_FILE, [t.model_dump() for t in _TASKS_CACHE])


# ──────────────────────────────────────────────────────────────────────────────
# Alert Model
# ──────────────────────────────────────────────────────────────────────────────

def _classify_criticality(title: str, summary: str) -> str:
    """
    Heuristic criticality scoring based on keywords.
    HIGH = safety-critical changes, LOW = editorial/informational.
    """
    text = (title + " " + summary).lower()
    high_kw = ["safety", "airworthiness directive", "emergency", "mandatory", "ad ", "part-145",
               "accident", "serious incident", "unsafe condition"]
    medium_kw = ["amendment", "revision", "update", "change", "new rule", "consultation",
                 "opinion", "npa", "implementing rule"]

    if any(kw in text for kw in high_kw):
        return "HIGH"
    if any(kw in text for kw in medium_kw):
        return "MEDIUM"
    return "LOW"


def _extract_rule_ids(text: str) -> list:
    """Extract EASA-style rule IDs from text."""
    return list(set(EASA_RULE_ID_PATTERN.findall(text)))


# ──────────────────────────────────────────────────────────────────────────────
# Feed Monitor
# ──────────────────────────────────────────────────────────────────────────────

def scan_rss_feeds() -> List[Alert]:
    """
    Scans all EASA RSS feeds for new entries not yet in our alert store.
    Returns list of NEW alert dicts.
    """
    _init_dirs()
    existing_alerts = _load_alerts()
    existing_ids = {a.feed_id for a in existing_alerts}

    new_alerts = []

    for feed_name, feed_url in RSS_FEEDS.items():
        try:
            session = requests.Session()
            session.headers.update({"User-Agent": USER_AGENT})
            resp = session.get(feed_url, timeout=15)
            resp.raise_for_status()
            feed = feedparser.parse(resp.text)

            for entry in feed.entries:
                feed_id = entry.get("id", entry.get("link", ""))
                if not feed_id or feed_id in existing_ids:
                    continue

                title = entry.get("title", "Untitled")
                summary = entry.get("summary", entry.get("description", ""))
                link = entry.get("link", "")
                published = ""
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    published = datetime.datetime.fromtimestamp(
                        time.mktime(entry.published_parsed)
                    ).isoformat()
                elif hasattr(entry, "published"):
                    published = entry.published

                criticality = _classify_criticality(title, summary)
                rule_ids = _extract_rule_ids(title + " " + summary)

                alert = Alert(
                    feed_id=feed_id,
                    feed_source=feed_name,
                    title=title,
                    summary=summary[:500],
                    link=link,
                    published=published or datetime.datetime.now().isoformat(),
                    detected_at=datetime.datetime.now().isoformat(),
                    criticality=criticality,
                    rule_ids=rule_ids,
                    status="new",
                    impact_analysis=None,
                )
                new_alerts.append(alert)
                existing_ids.add(feed_id)

        except Exception as e:
            print(f"Failed to scan feed '{feed_name}': {e}")
            continue

    # Persist all alerts
    if new_alerts:
        existing_alerts.extend(new_alerts)
        flush_to_disk()
        print(f"Watchdog: {len(new_alerts)} new alert(s) detected.")

    return new_alerts


def get_all_alerts() -> List[Alert]:
    """Returns all alerts, newest first."""
    alerts = _load_alerts()
    return sorted(alerts, key=lambda a: a.detected_at, reverse=True)


def get_new_alerts_count() -> int:
    """Returns count of alerts with status='new'."""
    alerts = _load_alerts()
    return sum(1 for a in alerts if a.status == "new")


def mark_alert_reviewed(feed_id: str):
    """Mark an alert as reviewed."""
    alerts = _load_alerts()
    for a in alerts:
        if a.feed_id == feed_id:
            a.status = "reviewed"
    flush_to_disk()


def archive_alert(feed_id: str):
    """Archive an alert."""
    alerts = _load_alerts()
    for a in alerts:
        if a.feed_id == feed_id:
            a.status = "archived"
    flush_to_disk()


def update_alert_impact(feed_id: str, impact_analysis: dict):
    """Attach impact analysis results to an alert."""
    alerts = _load_alerts()
    for a in alerts:
        if a.feed_id == feed_id:
            a.impact_analysis = impact_analysis
    flush_to_disk()


# ──────────────────────────────────────────────────────────────────────────────
# Compliance Task Management
# ──────────────────────────────────────────────────────────────────────────────

def create_compliance_task(
    rule_id: str,
    target_manual_section: str,
    suggested_change: str,
    alert_feed_id: str = "",
    criticality: str = "MEDIUM",
) -> ComplianceTask:
    """Creates a compliance task and persists it."""
    task = ComplianceTask(
        task_id=f"CT-{rule_id}-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}",
        rule_id=rule_id,
        target_manual_section=target_manual_section,
        suggested_change=suggested_change,
        alert_feed_id=alert_feed_id,
        criticality=criticality,
        status="Pending",
        created_at=datetime.datetime.now().isoformat(),
        implemented_at=None,
    )
    tasks = _load_tasks()
    tasks.append(task)
    flush_to_disk()
    return task


def get_all_tasks() -> List[ComplianceTask]:
    """Returns all compliance tasks, newest first."""
    tasks = _load_tasks()
    return sorted(tasks, key=lambda t: t.created_at, reverse=True)


def get_pending_tasks_count() -> int:
    """Returns count of pending tasks."""
    tasks = _load_tasks()
    return sum(1 for t in tasks if t.status == "Pending")


def mark_task_implemented(task_id: str):
    """Mark a task as implemented."""
    tasks = _load_tasks()
    for t in tasks:
        if t.task_id == task_id:
            t.status = "Implemented"
            t.implemented_at = datetime.datetime.now().isoformat()
    flush_to_disk()


def mark_task_in_progress(task_id: str):
    """Mark a task as in progress."""
    tasks = _load_tasks()
    for t in tasks:
        if t.task_id == task_id:
            t.status = "In Progress"
    flush_to_disk()


def run_impact_analysis(alert: Alert, engine) -> dict:
    """
    Runs the Researcher Agent to assess impact of a new rule on the uploaded manual.
    Returns an impact analysis dict.
    """
    if not engine or not engine.vectorstore:
        return {"error": "Engine not initialized. Run a Compliance Audit first."}

    title = alert.title
    summary = alert.summary
    rule_ids = alert.rule_ids
    query = f"{title} {summary}"

    # Hybrid search to find affected manual sections
    scored_rules = engine.hybrid_search(query, k=5)

    # Check if manual chunks are affected
    affected_sections = []
    if engine.manual_chunks:
        for chunk in engine.manual_chunks:
            chunk_text = f"{chunk.section_title} {chunk.content}".lower()
            # Check if any rule IDs or key terms from the alert match
            relevant = False
            for rid in rule_ids:
                if rid.lower() in chunk_text:
                    relevant = True
                    break
            if not relevant:
                alert_terms = title.lower().split()
                match_count = sum(1 for t in alert_terms if len(t) > 4 and t in chunk_text)
                if match_count >= 3:
                    relevant = True

            if relevant:
                affected_sections.append({
                    "page": chunk.page_number,
                    "section": chunk.section_title,
                    "snippet": chunk.content[:200],
                })

    # Determine conflict level
    if affected_sections:
        conflict_level = "HIGH" if len(affected_sections) >= 3 else "MEDIUM"
    else:
        conflict_level = "LOW"

    impact = {
        "affected_sections": affected_sections[:10],
        "related_rules": [{"id": r.id, "title": r.source_title, "score": f"{s:.3f}"} for r, s in scored_rules[:5]],
        "conflict_level": conflict_level,
        "summary": f"{len(affected_sections)} manual section(s) potentially affected by this regulatory change.",
    }

    # Auto-create compliance tasks for affected sections
    for section in affected_sections[:5]:
        create_compliance_task(
            rule_id=rule_ids[0] if rule_ids else "UNKNOWN",
            target_manual_section=f"Page {section['page']}, {section['section']}",
            suggested_change=f"Review and update to reflect: {title}",
            alert_feed_id=alert.feed_id,
            criticality=alert.criticality,
        )

    return impact
