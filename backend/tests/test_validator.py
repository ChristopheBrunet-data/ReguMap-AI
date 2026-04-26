import unittest
from unittest.mock import MagicMock
from agents.symbolic_validator import SymbolicValidator
from api_pkg.schemas import ValidationTrace

class TestSymbolicValidator(unittest.TestCase):
    def setUp(self):
        # Mocking the Neo4j Driver and session
        self.mock_driver = MagicMock()
        self.mock_session = self.mock_driver.session.return_value.__enter__.return_value
        self.validator = SymbolicValidator(self.mock_driver)

    def test_valid_reference_check(self):
        """
        Scenario: LLM cites an existing node.
        """
        # Mocking Neo4j records
        mock_record = {"node_id": "ORO.FTL.210", "node_hash": "hash_abc_123"}
        self.mock_session.run.return_value = [mock_record]
        
        assertion = "Based on ORO.FTL.210, you are compliant."
        trace = self.validator.validate_assertion(assertion)
        
        self.assertTrue(trace.is_valid)
        self.assertIn("ORO.FTL.210", trace.verified_nodes)
        self.assertEqual(len(trace.missing_nodes), 0)

    def test_hallucination_rejection(self):
        """
        Scenario: LLM cites a non-existent node (hallucination).
        """
        self.mock_session.run.return_value = [] # Nothing found
        
        assertion = "Based on ORO.FTL.999, you are compliant."
        trace = self.validator.validate_assertion(assertion)
        
        self.assertFalse(trace.is_valid)
        self.assertIn("ORO.FTL.999", trace.missing_nodes)
        self.assertIsNotNone(trace.error_message)
        self.assertIn("ERR_DATA_NOT_FOUND", trace.error_message)

    def test_no_evidence_rejection(self):
        """
        Scenario: Assertion contains no regulatory IDs.
        """
        assertion = "You are compliant."
        trace = self.validator.validate_assertion(assertion)
        
        self.assertFalse(trace.is_valid)
        self.assertIn("ERR_NO_EVIDENCE", trace.error_message)

if __name__ == "__main__":
    unittest.main()
