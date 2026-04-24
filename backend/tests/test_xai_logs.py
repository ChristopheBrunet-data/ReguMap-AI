import unittest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
import sys
import os

# Add backend to sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

# Import the FastAPI app
from api_pkg.main import app
from api_pkg.dependencies import get_engine, get_neo4j_driver
from api_pkg.schemas import ValidationTrace

class TestXAILogs(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        
        # Mocking the engine and driver
        self.mock_engine = MagicMock()
        self.mock_driver = MagicMock()
        
        # Override dependencies
        app.dependency_overrides[get_engine] = lambda: self.mock_engine
        app.dependency_overrides[get_neo4j_driver] = lambda: self.mock_driver

    def tearDown(self):
        app.dependency_overrides = {}

    def test_ask_endpoint_traceability(self):
        """
        Verify that /ask returns a complete TraceabilityLog.
        """
        # Mock engine response
        self.mock_engine.answer_regulatory_question.return_value = "Verified compliance with ORO.FTL.210."
        
        # Mock validator (internal to orchestrator, we mock the query engine response)
        with patch("agents.orchestrator.SymbolicValidator.validate_references") as mock_validate:
            mock_validate.return_value = ValidationTrace(
                is_valid=True,
                verified_nodes=["ORO.FTL.210"],
                cryptographic_hashes={"ORO.FTL.210": "abc123sha256"}
            )
            
            response = self.client.post("/api/v1/audit/ask", params={"query": "Am I compliant?"})
            
            # 1. Check HTTP Status
            self.assertEqual(response.status_code, 200)
            
            payload = response.json()
            
            # 2. Check XAI presence
            self.assertIn("traceability_log", payload)
            self.assertIn("cryptographic_hashes", payload["traceability_log"])
            self.assertIn("validation_query", payload["traceability_log"])
            
            # 3. Check data integrity
            hashes = payload["traceability_log"]["cryptographic_hashes"]
            self.assertEqual(hashes["ORO.FTL.210"], "abc123sha256")
            
            # Print the payload for report
            import json
            print("\n--- XAI PAYLOAD JSON ---")
            print(json.dumps(payload, indent=4))
            print("------------------------\n")

if __name__ == "__main__":
    unittest.main()
