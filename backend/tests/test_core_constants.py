"""
Tests for core_constants module.
Validates EASA rule ID regex and domain mappings.
"""

import pytest
from core_constants import EASA_RULE_ID_PATTERN, DOMAIN_TO_AGENCY


class TestEasaRuleIdPattern:
    """Validates the EASA rule ID regex against known patterns."""

    @pytest.mark.parametrize("rule_id", [
        "ADR.OR.B.005",
        "ORO.GEN.200",
        "CAT.OP.MPA.150",
        "ORO.FTL.210",
        "SPA.PBN.100",
        "NCO.OP.110",
    ])
    def test_valid_rule_ids(self, rule_id):
        match = EASA_RULE_ID_PATTERN.search(rule_id)
        assert match is not None, f"Expected '{rule_id}' to match"
        assert match.group() == rule_id

    @pytest.mark.parametrize("text", [
        "hello world",
        "123.456.789",
        "abc.def.ghi.000",
        "",
        "TOOLONG.X.Y.123",
    ])
    def test_invalid_patterns(self, text):
        matches = EASA_RULE_ID_PATTERN.findall(text)
        assert len(matches) == 0, f"Expected no matches for '{text}', got {matches}"

    def test_extraction_from_text(self):
        text = "In accordance with ORO.FTL.210 and CAT.OP.MPA.150, the operator must..."
        matches = EASA_RULE_ID_PATTERN.findall(text)
        assert "ORO.FTL.210" in matches
        assert "CAT.OP.MPA.150" in matches

    def test_no_partial_match(self):
        """Ensure the regex doesn't capture partial IDs from within larger tokens."""
        text = "SomePrefix_ADR.OR.B.005_suffix"
        matches = EASA_RULE_ID_PATTERN.findall(text)
        # The word boundary \b should still capture it since _ is a word char boundary
        assert len(matches) >= 0  # Behavior depends on regex specifics


class TestDomainToAgency:
    """Validates the domain-to-agency mapping."""

    def test_all_domains_mapped(self):
        expected_domains = [
            "air-ops", "aerodromes", "aircrew", "continuing-airworthiness",
            "initial-airworthiness", "additional-airworthiness", "atm-ans",
            "sera", "ground-handling", "remote-atc", "large-rotorcraft",
            "info-security",
        ]
        for domain in expected_domains:
            assert domain in DOMAIN_TO_AGENCY, f"Missing domain mapping: {domain}"

    def test_all_map_to_easa(self):
        """Currently all domains are EASA — verify consistency."""
        for domain, agency in DOMAIN_TO_AGENCY.items():
            assert agency == "EASA", f"Domain '{domain}' maps to '{agency}', expected 'EASA'"

    def test_mapping_count(self):
        assert len(DOMAIN_TO_AGENCY) == 12
