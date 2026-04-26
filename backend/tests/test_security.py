import unittest
from security.presidio_engine import DataSanitizer
from agents.orchestrator import ComplianceOrchestrator
from unittest.mock import MagicMock
from api_pkg.schemas import ValidationTrace

class TestSecurityAnonymization(unittest.TestCase):
    def setUp(self):
        self.sanitizer = DataSanitizer()

    def test_pii_deidentification(self):
        """
        Verify that sensitive names and phones are masked.
        """
        input_text = "Captain John Doe reported a defect on SN-12345, contact him at 555-0199."
        clean_text, signature = self.sanitizer.sanitize_prompt(input_text)
        
        self.assertNotIn("John Doe", clean_text)
        self.assertNotIn("555-0199", clean_text)
        self.assertIn("<PERSON>", clean_text)
        self.assertIn("<PHONE_NUMBER>", clean_text)
        self.assertIn("PERSON", signature)
        self.assertIn("PHONE_NUMBER", signature)

    def test_aviation_pii_deidentification(self):
        """
        Verify that aviation-specific identifiers (MSN, Tail Numbers) are masked.
        """
        input_text = "Aircraft N12345 (MSN 9876) has a defect."
        clean_text, signature = self.sanitizer.sanitize_prompt(input_text)
        
        self.assertNotIn("N12345", clean_text)
        self.assertNotIn("9876", clean_text)
        self.assertIn("<TAIL_NUMBER>", clean_text)
        self.assertIn("<MSN>", clean_text)
        self.assertIn("TAIL_NUMBER", signature)
        self.assertIn("MSN", signature)

    def test_orchestrator_integration(self):
        """
        Verify that the orchestrator uses the sanitized query for reasoning.
        """
        mock_validator = MagicMock()
        # Mocking validator success
        mock_validator.validate_assertion.return_value = ValidationTrace(
            is_valid=True,
            verified_nodes=["ADR.OR.B.005"],
            cryptographic_hashes={"ADR.OR.B.005": "hash"}
        )
        
        orchestrator = ComplianceOrchestrator(mock_validator)
        
        sensitive_query = "Contact John Doe for ADR.OR.B.005."
        state = orchestrator.run(sensitive_query)
        
        # Check that the researcher response used the sanitized query
        self.assertNotIn("John Doe", state.researcher_response)
        self.assertIn("<PERSON>", state.researcher_response)
        self.assertTrue(state.traceability_log.anonymized)

if __name__ == "__main__":
    unittest.main()
