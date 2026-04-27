import unittest
import os
import logging
from ingestion.easa_parser import parse_easa_xml, validate_xml_against_xsd, XMLValidationError
from ingestion.contracts import RegulatoryNode

# Silence logging during tests
logging.getLogger('ingestion.easa_parser').setLevel(logging.ERROR)

class TestEASAParser(unittest.TestCase):
    def setUp(self):
        self.fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")
        self.xsd_path = r"C:\Users\chris\.gemini\antigravity\playground\charged-triangulum\SOURCE\easa-erules-xml-export-schema-1.0.0\EASA-eRules-XML-Export-Schema-1.0.0.xsd"
        self.sample_xml = os.path.join(self.fixtures_dir, "sample_easa.xml")

    def test_validation_failure(self):
        """Ensure that invalid XML raises XMLValidationError."""
        bad_xml = os.path.join(self.fixtures_dir, "bad_easa.xml")
        with open(bad_xml, "w") as f:
            f.write("<invalid_root>No namespace</invalid_root>")
        
        try:
            with self.assertRaises(XMLValidationError):
                validate_xml_against_xsd(bad_xml, self.xsd_path)
        finally:
            if os.path.exists(bad_xml):
                os.remove(bad_xml)

    def test_parsing_hierarchy(self):
        """Verify that the parser correctly extracts hierarchy and metadata."""
        # Note: We parse WITHOUT validation here because our sample has content 
        # that might not be in the metadata-only XSD.
        nodes = parse_easa_xml(self.sample_xml, xsd_path=None)
        
        self.assertGreater(len(nodes), 0)
        
        # Find ADR.OR.A.005
        topic = next((n for n in nodes if n.node_id == "ADR.OR.A.005"), None)
        self.assertIsNotNone(topic)
        self.assertEqual(topic.node_type, "IR")
        self.assertIn("test content", topic.content)
        self.assertEqual(topic.metadata.get("Domain"), "Aerodromes;")
        
        # Find AMC1
        amc = next((n for n in nodes if n.node_id == "AMC1 ADR.OR.A.015"), None)
        self.assertIsNotNone(amc)
        self.assertEqual(amc.node_type, "AMC")
        self.assertEqual(amc.parent_id, "ADR.OR.A.015") 
        # Wait, the hierarchy logic might need to be smarter about skipping er:toc if it's just a wrapper.
        
        # Check Section (Heading)
        section = next((n for n in nodes if n.node_type == "Section"), None)
        self.assertIsNotNone(section)
        self.assertEqual(section.title, "SUBPART A — GENERAL")

    def test_strict_validation_blocks_ingestion(self):
        """Ensure that if xsd_path is provided, invalid XML blocks parsing."""
        bad_xml = os.path.join(self.fixtures_dir, "bad_easa.xml")
        with open(bad_xml, "w") as f:
            f.write("<er:document xmlns:er='http://www.easa.europa.eu/erules-export'><er:bad/></er:document>")
        
        try:
            with self.assertRaises(XMLValidationError):
                parse_easa_xml(bad_xml, self.xsd_path)
        finally:
            if os.path.exists(bad_xml):
                os.remove(bad_xml)

if __name__ == "__main__":
    unittest.main()
