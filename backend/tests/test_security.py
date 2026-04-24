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

    def test_orchestrator_integration(self):
        """
        Verify that the orchestrator uses the sanitized query for LLM calls.
        """
        mock_engine = MagicMock()
        mock_validator = MagicMock()
        mock_engine.answer_regulatory_question.return_value = "Response from AI."
        
        # Mocking validator success
        mock_validator.validate_references.return_value = ValidationTrace(
            is_valid=True,
            verified_nodes=[],
            cryptographic_hashes={}
        )
        
        orchestrator = ComplianceOrchestrator(mock_engine, mock_validator)
        
        sensitive_query = "Contact John Doe for ADR.OR.B.005."
        orchestrator.run(sensitive_query)
        
        # Check that the engine received the sanitized version
        # It should contain <PERSON> instead of John Doe
        call_args = mock_engine.answer_regulatory_question.call_args[0][0]
        self.assertNotIn("John Doe", call_args)
        self.assertIn("<PERSON>", call_args)

if __name__ == "__main__":
    unittest.main()
