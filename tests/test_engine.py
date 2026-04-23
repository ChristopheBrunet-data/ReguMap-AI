"""
Tests for ComplianceEngine initialization and BM25 index construction.
Uses mocked LLM to avoid API calls.
"""

import pytest
from unittest.mock import patch, MagicMock
from schemas import EasaRequirement


class TestEngineInit:
    """Tests engine initialization without heavy dependencies."""

    @patch("engine.ChatGoogleGenerativeAI")
    @patch("engine.ComplianceBoard")
    @patch("engine.RegulatoryKnowledgeGraph")
    def test_init_creates_engine(self, mock_graph, mock_board, mock_llm):
        from engine import ComplianceEngine
        engine = ComplianceEngine(api_key="test-key")
        assert engine._api_key == "test-key"
        assert engine.vectorstore is None
        assert engine.bm25_index is None
        assert engine.manual_chunks == []

    @patch("engine.ChatGoogleGenerativeAI")
    @patch("engine.ComplianceBoard")
    @patch("engine.RegulatoryKnowledgeGraph")
    def test_set_manual_chunks(self, mock_graph, mock_board, mock_llm, sample_manual_chunk):
        from engine import ComplianceEngine
        engine = ComplianceEngine(api_key="test-key")
        engine.set_manual_chunks([sample_manual_chunk])
        assert len(engine.manual_chunks) == 1
        assert engine.pre_filtered is False

    @patch("engine.ChatGoogleGenerativeAI")
    @patch("engine.ComplianceBoard")
    @patch("engine.RegulatoryKnowledgeGraph")
    def test_evaluate_without_prefilter_raises(self, mock_graph, mock_board, mock_llm, sample_requirement):
        from engine import ComplianceEngine
        engine = ComplianceEngine(api_key="test-key")
        with pytest.raises(ValueError, match="Pre-filtering not run"):
            engine.evaluate_compliance(sample_requirement)
