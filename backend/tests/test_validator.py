import unittest
from unittest.mock import MagicMock
from agents.symbolic_validator import SymbolicValidator
from api_pkg.schemas import ValidationTrace

class TestSymbolicValidator(unittest.TestCase):
    def setUp(self):
        # Mocking the Neo4j Driver and its verify_nodes_exist behavior
        self.mock_driver = MagicMock()
        self.validator = SymbolicValidator(self.mock_driver)

    def test_valid_reference_check(self):
        """
        Scenario: LLM cites an existing node.
        """
        # Mocking the query engine result (injected via patching or just mock the dependency)
        # For simplicity, we patch the verify_nodes_exist call
        import agents.symbolic_validator as sv
        sv.verify_nodes_exist = MagicMock(return_value={"ORO.FTL.210": "hash_abc_123"})
        
        claimed = ["ORO.FTL.210"]
        trace = self.validator.validate_references(claimed)
        
        self.assertTrue(trace.is_valid)
        self.assertIn("ORO.FTL.210", trace.verified_nodes)
        self.assertEqual(len(trace.missing_nodes), 0)

    def test_hallucination_rejection(self):
        """
        Scenario: LLM cites a non-existent node (hallucination).
        """
        import agents.symbolic_validator as sv
        sv.verify_nodes_exist = MagicMock(return_value={}) # Nothing found
        
        claimed = ["ORO.FTL.999"]
        trace = self.validator.validate_references(claimed)
        
        self.assertFalse(trace.is_valid)
        self.assertIn("ORO.FTL.999", trace.missing_nodes)
        self.assertIsNotNone(trace.error_message)
        self.assertIn("Hallucination Detected", trace.error_message)

if __name__ == "__main__":
    unittest.main()
