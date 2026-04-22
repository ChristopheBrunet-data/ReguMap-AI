import xml.etree.ElementTree as ET

def generate_complex_easa_xml(filename: str = "sample_easa.xml"):
    print(f"Generating complex EASA XML: {filename}...")
    
    # Namespaces
    w_ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    ET.register_namespace("w", w_ns)
    
    root = ET.Element("easy_access_rules", version="2026.1")
    
    # SDT Content Map
    sdt_content = {
        "101": "The operator shall establish, implement and maintain flight time and duty period limitations. The maximum basic daily flight duty period shall be 13 hours. This FDP shall be reduced by 30 minutes for each sector from the third sector onwards.",
        "102": "The operator shall establish a fuel policy for the purpose of flight planning and in-flight re-planning to ensure that every flight carries sufficient fuel for the planned operation and reserves to cover deviations from the planned operation.",
        "103": "The aerodrome operator shall establish and maintain a management system that includes clearly defined lines of responsibility."
    }
    
    # Create w:sdt elements
    for sdt_id, text in sdt_content.items():
        sdt = ET.SubElement(root, f"{{{w_ns}}}sdt")
        sdt_pr = ET.SubElement(sdt, f"{{{w_ns}}}sdtPr")
        w_id = ET.SubElement(sdt_pr, f"{{{w_ns}}}id")
        w_id.set(f"{{{w_ns}}}val", sdt_id)
        t_elem = ET.SubElement(sdt, f"{{{w_ns}}}t")
        t_elem.text = text
    
    # Create topic elements
    topics = [
        ("ORO.FTL.210", "Flight times and duty periods", "101", "Air Operations"),
        ("CAT.OP.MPA.150", "Fuel policy", "102", "Air Operations"),
        ("ADR.OR.B.005", "Management System", "103", "Aerodromes")
    ]
    
    for rid, title, sid, dom in topics:
        topic = ET.SubElement(root, "topic")
        topic.set("ERulesId", rid)
        topic.set("source-title", title)
        topic.set("sdt-id", sid)
        topic.set("Domain", dom)
    
    tree = ET.ElementTree(root)
    tree.write(filename, encoding="utf-8", xml_declaration=True)
    print(f"Updated {filename} with Word-SDT structure.")

if __name__ == "__main__":
    generate_complex_easa_xml()
