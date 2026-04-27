from lxml import etree
from typing import List, Dict
import os

from ingestion.contracts import RegulatoryNode
from ingestion.hasher import generate_node_hash

def parse_easa_xml(file_path: str) -> List[RegulatoryNode]:
    """
    Parses EASA Easy Access Rules XML into a hierarchical DOM structure using lxml.
    Instantiates strictly typed RegulationNode objects for downstream ingestion.
    """
    try:
        tree = etree.parse(file_path)
    except Exception as e:
        print(f"[!] Failed to parse XML with lxml: {e}")
        return []
        
    root = tree.getroot()
    
    # 1. Map content by SDT ID
    # The EASA XML often uses WordProcessingML namespaces for text blocks
    namespaces = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    content_map: Dict[str, str] = {}
    
    # Extract text from w:sdt tags (Structured Document Tags)
    for sdt in root.xpath('.//w:sdt', namespaces=namespaces):
        sdt_id_elem = sdt.find('.//w:id', namespaces=namespaces)
        text_elem = sdt.find('.//w:t', namespaces=namespaces)
        
        if sdt_id_elem is not None and text_elem is not None and text_elem.text:
            sdt_id = sdt_id_elem.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val')
            content_map[sdt_id] = text_elem.text.strip()

    # Fallback/Direct parsing: if XML uses <er:topic> or direct <topic> tags
    # Let's search for any element ending in 'topic'
    nodes: List[RegulationNode] = []
    topics = root.xpath('//*[local-name()="topic"]')
    
    for topic in topics:
        erules_id = topic.get('ERulesId')
        sdt_id = topic.get('sdt-id')
        
        # Determine content: use content_map if sdt-id exists, otherwise extract raw text from children
        if sdt_id and sdt_id in content_map:
            content = content_map[sdt_id]
        else:
            # Extract all text inside the topic tag
            content = "".join(topic.itertext()).strip()
            
        if not content:
            content = "No textual content available."

        # EASA regulations must have a node_id
        node_id = erules_id or f"UNKNOWN_{sdt_id or id(topic)}"
        
        # Determine legal category
        category = "Regulation" # Default
        if erules_id:
            if "AMC" in erules_id:
                category = "AMC"
            elif "GM" in erules_id:
                category = "GM"
            elif "CS" in erules_id:
                category = "CS"
            elif "IR" in erules_id:
                category = "IR"
                
        # Generate the cryptographic hash
        sha256_hash = generate_node_hash(node_id, content)
        
        parent_id = topic.get('parent-id')
        title = topic.get('source-title')

        try:
            node = RegulatoryNode(
                node_id=node_id,
                title=title,
                content=content,
                content_hash=sha256_hash,
                parent_id=parent_id,
                node_type="Regulation",
                metadata={"category": category}
            )
            nodes.append(node)
        except Exception as e:
            print(f"[!] Validation error skipping node {node_id}: {e}")
            
    return nodes

if __name__ == "__main__":
    sample_path = os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures", "sample_easa.xml")
    if os.path.exists(sample_path):
        results = parse_easa_xml(sample_path)
        for res in results[:5]: # print first 5
            print(f"[{res.category}] {res.node_id}")
            print(f"Hash: {res.sha256_hash}")
            print(f"Content: {res.content[:50]}...")
            print("-" * 20)
        print(f"Total nodes parsed: {len(results)}")
    else:
        print(f"Sample not found at {sample_path}")
