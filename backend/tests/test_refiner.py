"""
Tests for the QueryRefiner module.
"""

import pytest
from refiner import RefinedQuery


class TestRefinedQueryModel:
    """Validates the RefinedQuery Pydantic model."""

    def test_construction(self):
        r = RefinedQuery(
            Search_Keywords="portable fire extinguisher safety equipment",
            Refined_Question="What are the requirements for portable fire extinguishers?",
        )
        assert "fire extinguisher" in r.Search_Keywords
        assert r.Refined_Question.startswith("What")

    def test_missing_field(self):
        with pytest.raises(Exception):
            RefinedQuery(Search_Keywords="test")  # missing Refined_Question
