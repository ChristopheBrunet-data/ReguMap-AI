import unittest
from ingestion.hasher import generate_node_hash

class TestRegulatoryHasher(unittest.TestCase):
    def test_deterministic_hashing(self):
        """
        Two nodes with same ID and content must produce identical hashes.
        """
        id_1 = "ORO.GEN.200"
        content_1 = "Management system shall include..."
        
        h1 = generate_node_hash(id_1, content_1)
        h2 = generate_node_hash(id_1, content_1)
        
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64) # SHA-256 hex length

    def test_hashing_sensitivity(self):
        """
        Changing a single character must change the hash completely.
        """
        id_1 = "ORO.GEN.200"
        content_1 = "Management system shall include..."
        content_2 = "Management system shall include.." # One dot missing
        
        h1 = generate_node_hash(id_1, content_1)
        h2 = generate_node_hash(id_1, content_2)
        
        self.assertNotEqual(h1, h2)
        
    def test_whitespace_normalization(self):
        """
        Trailing whitespaces should not affect the hash (normalization).
        """
        id_1 = "ORO.GEN.200"
        content_1 = "Text "
        content_2 = "Text"
        
        h1 = generate_node_hash(id_1, content_1)
        h2 = generate_node_hash(id_1, content_2)
        
        self.assertEqual(h1, h2)

if __name__ == "__main__":
    unittest.main()
