"""
Tests for the regulatory watchdog module.
Covers alert classification, rule ID extraction, task lifecycle, and cache management.
"""

import os
import json
import pytest
from unittest.mock import patch
import regulatory_watchdog as watchdog
from schemas import Alert, ComplianceTask


class TestCriticalityClassification:
    """Tests the heuristic criticality scoring."""

    def test_high_criticality(self):
        result = watchdog._classify_criticality(
            "Emergency Airworthiness Directive",
            "Unsafe condition detected in landing gear assembly"
        )
        assert result == "HIGH"

    def test_medium_criticality(self):
        result = watchdog._classify_criticality(
            "Amendment to Part-ADR",
            "Revision of aerodrome management system requirements"
        )
        assert result == "MEDIUM"

    def test_low_criticality(self):
        result = watchdog._classify_criticality(
            "General Information",
            "Publication schedule for Q3 2026"
        )
        assert result == "LOW"

    def test_safety_keyword_triggers_high(self):
        result = watchdog._classify_criticality("Safety bulletin", "routine check")
        assert result == "HIGH"


class TestRuleIdExtraction:
    """Tests EASA rule ID extraction from text."""

    def test_extract_single(self):
        ids = watchdog._extract_rule_ids("Amendment to ADR.OR.B.005")
        assert "ADR.OR.B.005" in ids

    def test_extract_multiple(self):
        ids = watchdog._extract_rule_ids("Changes to ORO.FTL.210 and CAT.OP.MPA.150")
        assert "ORO.FTL.210" in ids
        assert "CAT.OP.MPA.150" in ids

    def test_extract_none(self):
        ids = watchdog._extract_rule_ids("No regulatory IDs here")
        assert ids == []

    def test_extract_deduplicated(self):
        ids = watchdog._extract_rule_ids("ADR.OR.B.005 text ADR.OR.B.005 again")
        assert ids.count("ADR.OR.B.005") == 1


class TestTaskLifecycle:
    """Tests compliance task creation and state transitions."""

    def test_create_task(self, temp_dir):
        # Reset global cache
        watchdog._TASKS_CACHE = None
        with patch.object(watchdog, 'TASKS_FILE', os.path.join(temp_dir, 'tasks.json')):
            with patch.object(watchdog, 'ALERTS_DIR', temp_dir):
                task = watchdog.create_compliance_task(
                    rule_id="ADR.OR.B.005",
                    target_manual_section="Page 42, Section 4.1",
                    suggested_change="Update management system docs",
                    alert_feed_id="test-alert-1",
                    criticality="HIGH",
                )
                assert isinstance(task, ComplianceTask)
                assert task.status == "Pending"
                assert task.rule_id == "ADR.OR.B.005"
                assert task.task_id.startswith("CT-ADR.OR.B.005-")

    def test_alert_model_attributes(self, sample_alert):
        """Verify that Alert Pydantic model uses attribute access (not dict)."""
        # This test validates the BUG-4 fix
        assert hasattr(sample_alert, "criticality")
        assert hasattr(sample_alert, "title")
        assert hasattr(sample_alert, "feed_id")
        assert sample_alert.criticality == "MEDIUM"
        assert sample_alert.title == "Amendment to Part-ADR"

    def test_task_model_attributes(self, sample_compliance_task):
        """Verify that ComplianceTask Pydantic model uses attribute access."""
        assert hasattr(sample_compliance_task, "rule_id")
        assert hasattr(sample_compliance_task, "task_id")
        assert hasattr(sample_compliance_task, "status")
        assert sample_compliance_task.status == "Pending"
