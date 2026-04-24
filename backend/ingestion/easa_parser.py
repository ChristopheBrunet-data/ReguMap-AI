import xml.etree.ElementTree as ET
from typing import List, Optional, Dict
from ingestion.contracts import RegulatoryNode

def parse_easa_xml(file_path: str) -> List[RegulatoryNode]:
    """
    Parses EASA Easy Access Rules XML into a hierarchical DOM structure.
    Standardizes nodes into RegulatoryNode objects for downstream ingestion.
    """
    tree = ET.parse(file_path)
    root = tree.getroot()
    
    # 1. Map content by SDT ID
    # Note: Dealing with namespaces (w:sdt, w:t)
    namespaces = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    content_map: Dict[str, str] = {}
    
    for sdt in root.findall('.//w:sdt', namespaces):
        sdt_id_elem = sdt.find('.//w:id', namespaces)
        text_elem = sdt.find('.//w:t', namespaces)
        
        if sdt_id_elem is not None and text_elem is not None:
            sdt_id = sdt_id_elem.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val')
            content_map[sdt_id] = text_elem.text

    # 2. Build RegulatoryNodes from topics
    nodes: List[RegulatoryNode] = []
    
    for topic in root.findall('topic'):
        erules_id = topic.get('ERulesId')
        sdt_id = topic.get('sdt-id')
        title = topic.get('source-title')
        domain = topic.get('Domain')
        parent_id = topic.get('parent-id')
        
        content = content_map.get(sdt_id, "")
        
        # Determine node type (Regulation by default for topics)
        node_type = "Regulation"
        if erules_id:
            if "AMC" in erules_id or "GM" in erules_id:
                node_type = "AMC/GM"
            
        node = RegulatoryNode(
            node_id=erules_id or f"UNKNOWN_{sdt_id}",
            title=title,
            content=content,
            parent_id=parent_id,
            node_type=node_type,
            metadata={
                "domain": domain,
                "sdt_id": sdt_id
            }
        )
        nodes.append(node)
        
    return nodes

if __name__ == "__main__":
    import os
    sample_path = os.path.join(os.path.dirname(__file__), "..", "sample_easa.xml")
    if os.path.exists(sample_path):
        results = parse_easa_xml(sample_path)
        for res in results:
            print(f"[{res.node_type}] {res.node_id}: {res.title}")
            print(f"Content: {res.content[:50]}...")
            print("-" * 20)
