import unittest
from unittest.mock import MagicMock, patch
from agents.orchestrator import ComplianceOrchestrator, ComplianceTimeoutError
from api_pkg.schemas import ValidationTrace

class TestComplianceOrchestrator(unittest.TestCase):
    def setUp(self):
        self.mock_validator = MagicMock()
        self.orchestrator = ComplianceOrchestrator(self.mock_validator)

    def test_auto_correction_loop(self):
        """
        Scenario: 
        1. Researcher hallucinates ORO.FTL.999.
        2. Validator rejects it.
        3. Researcher corrects and provides ORO.FTL.210.
        4. Validator accepts.
        """
        # --- Mocking Validator ---
        # 1st call is invalid, 2nd call is valid
        trace_fail = ValidationTrace(
            is_valid=False,
            missing_nodes=["ORO.FTL.999"],
            error_message="Hallucination Detected: ORO.FTL.999"
        )
        trace_success = ValidationTrace(
            is_valid=True,
            verified_nodes=["ORO.FTL.210"]
        )
        self.mock_validator.validate_assertion.side_effect = [trace_fail, trace_success]

        # --- Execution ---
        # Note: The mock implementation in orchestrator.py has hardcoded responses for now
        final_state = self.orchestrator.run("Check my flight time compliance.")

        # --- Assertions ---
        self.assertEqual(final_state.iteration_count, 2)
        self.assertTrue(final_state.validation_trace.is_valid)
        self.assertEqual(len(final_state.error_log), 1)

    def test_timeout_on_persistent_hallucination(self):
        """
        Scenario: Researcher keeps hallucinating after 3 attempts.
        """
        self.mock_validator.validate_assertion.return_value = ValidationTrace(
            is_valid=False,
            missing_nodes=["ORO.FTL.999"],
            error_message="Persistent Hallucination"
        )

        with self.assertRaises(ComplianceTimeoutError):
            self.orchestrator.run("Query")

if __name__ == "__main__":
    unittest.main()
