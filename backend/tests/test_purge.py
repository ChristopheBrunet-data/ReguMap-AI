import unittest
from unittest.mock import MagicMock, patch
import os
import json

# Import the utility classes
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from purge_obsolete_refs import AuditTrail, Neo4jPurger, VectorPurger

class TestPurgeUtility(unittest.TestCase):

    def test_audit_trail_hashing(self):
        audit = AuditTrail()
        audit.add_entry("TEST", "123", "Some content", "Reason")
        entry = audit.entries[0]
        self.assertEqual(entry["ref_id"], "123")
        # SHA-256 of "Some content"
        expected_hash = "9c6609fc5111405ea3f5bb3d1f6b5a5efd19a0cec53d85893fd96d265439cd5b"
        self.assertEqual(entry["content_hash"], expected_hash)

    @patch("purge_obsolete_refs.GraphDatabase.driver")
    def test_neo4j_dry_run(self, mock_driver):
        # Setup mock
        mock_session = MagicMock()
        mock_driver.return_value.session.return_value.__enter__.return_value = mock_session
        
        # Mock result for "find" query
        mock_record = {"id": 1, "n": {"title": "Ref CM-AS-001"}} # skip-compliance-check
        mock_session.run.return_value = [mock_record]

        purger = Neo4jPurger("uri", "user", "pass")
        purger.purge(dry_run=True)
        
        # Verify DETACH DELETE was NOT called
        for call in mock_session.run.call_args_list:
            self.assertNotIn("DETACH DELETE", call[0][0])
        
        self.assertEqual(len(purger.audit.entries), 1)

    @patch("purge_obsolete_refs.os.path.exists")
    @patch("purge_obsolete_refs.FAISS.load_local")
    @patch("purge_obsolete_refs.VectorPurger._decrypt_load")
    @patch("purge_obsolete_refs.HuggingFaceEmbeddings")
    def test_vector_purge_logic(self, mock_embeddings, mock_decrypt, mock_load, mock_exists):
        mock_exists.return_value = True
        mock_decrypt.return_value = "temp_path"
        
        # Mock FAISS instance
        mock_faiss = MagicMock()
        mock_load.return_value = mock_faiss
        
        # Mock docstore
        mock_doc = MagicMock()
        mock_doc.page_content = "This is about CM-AS-001" # skip-compliance-check
        mock_doc.metadata = {"id": "rule_1"}
        mock_faiss.docstore._dict = {"id_1": mock_doc}
        
        purger = VectorPurger("index_path")
        with patch("shutil.rmtree"), patch.object(VectorPurger, "_encrypt_save"): 
            purger.purge(dry_run=False)
        
        # Verify delete was called with the correct ID
        mock_faiss.delete.assert_called_with(["id_1"])

if __name__ == "__main__":
    unittest.main()
