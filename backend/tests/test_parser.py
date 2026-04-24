import unittest
import os
import xml.etree.ElementTree as ET
from pydantic import ValidationError
from ingestion.contracts import RegulatoryNode
from ingestion.easa_parser import parse_easa_xml

class TestRegulatoryParser(unittest.TestCase):
    def test_easa_hierarchy_logic(self):
        """
        Verify that children correctly inherit parent_id in the DOM structure.
        """
        # Mock XML with hierarchical structure
        xml_content = """<?xml version='1.0' encoding='utf-8'?>
        <easy_access_rules version="2026.1">
            <w:sdt xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                <w:sdtPr><w:id w:val="101" /></w:sdtPr>
                <w:t>Parent Content</w:t>
            </w:sdt>
            <w:sdt xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                <w:sdtPr><w:id w:val="102" /></w:sdtPr>
                <w:t>Child Content</w:t>
            </w:sdt>
            <topic ERulesId="PARENT.001" source-title="Parent" sdt-id="101" />
            <topic ERulesId="CHILD.001" source-title="Child" sdt-id="102" parent-id="PARENT.001" />
        </easy_access_rules>
        """
        test_file = "test_easa_mock.xml"
        with open(test_file, "w", encoding="utf-8") as f:
            f.write(xml_content)
            
        try:
            nodes = parse_easa_xml(test_file)
            self.assertEqual(len(nodes), 2)
            
            # Find the child node
            child = next(n for n in nodes if n.node_id == "CHILD.001")
            self.assertEqual(child.parent_id, "PARENT.001")
            self.assertEqual(child.content, "Child Content")
        finally:
            if os.path.exists(test_file):
                os.remove(test_file)

    def test_regulatory_node_validation(self):
        """
        Ensure Pydantic blocks malformed data (mandatory node_id).
        """
        # 1. Missing node_id
        with self.assertRaises(ValidationError):
            RegulatoryNode(
                content="Valid content",
                content_hash="hash123",
                node_type="Regulation"
            )
            
        # 2. Empty node_id
        with self.assertRaises(ValidationError):
            RegulatoryNode(
                node_id=" ",
                content="Valid content",
                content_hash="hash123",
                node_type="Regulation"
            )
            
        # 3. Valid node
        node = RegulatoryNode(
            node_id="VALID.001",
            content="Valid content",
            content_hash="hash123",
            node_type="Regulation"
        )
        self.assertEqual(node.node_id, "VALID.001")

if __name__ == "__main__":
    unittest.main()
