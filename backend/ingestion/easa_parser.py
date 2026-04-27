from lxml import etree
from typing import List, Dict, Any, Optional
import os
import logging

from ingestion.contracts import RegulatoryNode
from ingestion.hasher import generate_node_hash

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Namespaces
NAMESPACE_EASA = "http://www.easa.europa.eu/erules-export"
NAMESPACES = {'easa': NAMESPACE_EASA}

class XMLValidationError(Exception):
    """Raised when XML does not conform to XSD."""
    pass

def validate_xml_against_xsd(xml_path: str, xsd_path: str) -> None:
    """
    Validates an XML file against an XSD schema.
    Raises XMLValidationError if invalid.
    """
    if not os.path.exists(xsd_path):
        raise FileNotFoundError(f"XSD schema not found at {xsd_path}")
        
    try:
        with open(xsd_path, 'rb') as f:
            schema_root = etree.XML(f.read())
            schema = etree.XMLSchema(schema_root)
            
        with open(xml_path, 'rb') as f:
            xml_doc = etree.XML(f.read())
            
        if not schema.validate(xml_doc):
            error_msg = "\n".join([str(err) for err in schema.error_log])
            raise XMLValidationError(f"XML validation failed for {xml_path}:\n{error_msg}")
        logger.info(f"[✓] XML validation passed for {xml_path}")
    except etree.XMLSyntaxError as e:
        raise XMLValidationError(f"XML syntax error in {xml_path}: {e}")
    except Exception as e:
        if isinstance(e, XMLValidationError):
            raise e
        raise XMLValidationError(f"Unexpected error during validation: {e}")

def parse_easa_xml(file_path: str, xsd_path: Optional[str] = None) -> List[RegulatoryNode]:
    """
    Parses EASA Easy Access Rules XML into a hierarchical DOM structure.
    Strictly follows the EASA XSD and handles namespaces.
    """
    # T1 - Validation XSD
    if xsd_path:
        try:
            validate_xml_against_xsd(file_path, xsd_path)
        except XMLValidationError as e:
            logger.error(f"Blocking ingestion due to validation failure: {e}")
            raise

    try:
        tree = etree.parse(file_path)
        root = tree.getroot()
    except Exception as e:
        logger.error(f"Failed to parse XML file: {e}")
        return []

    nodes: List[RegulatoryNode] = []

    def map_rule_type(type_of_content: str) -> str:
        """Maps TypeOfContent attribute to short RuleType (IR, AMC, GM)."""
        if not type_of_content:
            return "Regulation"
        upper_type = type_of_content.upper()
        if "AMC" in upper_type:
            return "AMC"
        if "GM" in upper_type:
            return "GM"
        if "IR" in upper_type or "IMPLEMENTING RULE" in upper_type:
            return "IR"
        if "CS" in upper_type:
            return "CS"
        return "Regulation"

    def walk_toc(element: etree._Element, parent_id: Optional[str] = None):
        """Recursively traverses the TOC structure to extract topics and headings."""
        # T2 - Namespace Handling
        local_name = etree.QName(element).localname
        
        current_node_id = None
        
        if local_name in ("topic", "heading"):
            # T3 - Metadata Extraction
            metadata = {k: v for k, v in element.attrib.items()}
            
            erules_id = metadata.get('ERulesId')
            sdt_id = metadata.get('sdt-id')
            source_title = metadata.get('source-title') or metadata.get('title')
            
            # ERulesId becomes the node_id
            current_node_id = erules_id or sdt_id or f"gen_{hash(element)}"
            
            # T3 - Hierarchy (ParentIR)
            # Use ParentIR if available, otherwise fallback to the structural parent_id
            actual_parent_id = metadata.get('ParentIR') or parent_id
            
            # T4 - Content Extraction
            # Extract all text inside the element (including potential <content><para> children)
            content = "".join(element.itertext()).strip()
            if not content:
                content = source_title or "No textual content available."
            
            # Determine node_type
            type_of_content = metadata.get('TypeOfContent', '')
            node_type = map_rule_type(type_of_content)
            if local_name == "heading":
                node_type = "Section"

            # Cryptographic hash
            content_hash = generate_node_hash(current_node_id, content)
            
            try:
                node = RegulatoryNode(
                    node_id=current_node_id,
                    title=source_title,
                    content=content,
                    content_hash=content_hash,
                    parent_id=actual_parent_id,
                    node_type=node_type,
                    metadata=metadata
                )
                nodes.append(node)
            except Exception as e:
                logger.warning(f"Skipping malformed node {current_node_id}: {e}")

        # Recurse into children TOC elements
        # Only search for children in the EASA namespace
        children = element.xpath('./easa:toc | ./easa:heading | ./easa:topic', namespaces=NAMESPACES)
        for child in children:
            # Hierarchy: current node becomes the parent for its children
            walk_toc(child, parent_id=current_node_id or parent_id)

    # Start traversal from the top-level TOC
    top_toc = root.xpath('./easa:toc', namespaces=NAMESPACES)
    for toc in top_toc:
        walk_toc(toc)

    return nodes

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        path = sys.argv[1]
        xsd = sys.argv[2] if len(sys.argv) > 2 else None
        res = parse_easa_xml(path, xsd)
        print(f"Parsed {len(res)} nodes.")
    else:
        print("Usage: python easa_parser.py <xml_file> [xsd_file]")
