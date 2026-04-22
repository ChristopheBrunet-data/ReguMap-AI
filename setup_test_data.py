import os
import xml.etree.ElementTree as ET
from fpdf import FPDF

def generate_sample_easa_xml(filename: str = "sample_easa.xml"):
    """Generates a realistic EASA XML excerpt for testing."""
    print("Generating sample_easa.xml...")
    root = ET.Element("easy_access_rules")
    
    req1 = ET.SubElement(root, "rule", id="ADR.OR.B.005", level="Hard Law", reference="Part-ADR.OR.B.005")
    title = ET.SubElement(req1, "title")
    title.text = "Management System"
    content = ET.SubElement(req1, "content")
    content.text = "The aerodrome operator shall establish and maintain a management system that includes: (1) clearly defined lines of responsibility and accountability throughout the organisation, including a direct safety accountability of the accountable manager; (2) a description of the overall philosophies and principles of the organisation with regard to safety, referred to as the safety policy."
    
    tree = ET.ElementTree(root)
    tree.write(filename, encoding="utf-8", xml_declaration=True)
    print(f"Created {filename}")

def generate_sample_manual_pdf(filename: str = "sample_manual.pdf"):
    """Generates a realistic Airline Operator Manual PDF with headers to test parsing."""
    print("Generating sample_manual.pdf...")
    pdf = FPDF()
    pdf.add_page()
    
    # Title
    pdf.set_font("Arial", 'B', 24)
    pdf.cell(0, 20, "Aerodrome Manual", ln=True, align='C')
    pdf.ln(20)
    
    # Section 4
    pdf.set_font("Arial", 'B', 18)
    pdf.cell(0, 10, "Section 4: Management", ln=True)
    pdf.ln(5)
    
    # Section 4.1.1
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, "4.1.1 Leadership Commitment", ln=True)
    pdf.set_font("Arial", '', 12)
    pdf.multi_cell(0, 10, "The organization is led by the Accountable Manager, who assumes ultimate responsibility for safety performance. The AM maintains a direct line of accountability for the implementation and maintenance of the safety management system across all operational directorates.")
    
    pdf.output(filename)
    print(f"Created {filename}")

if __name__ == "__main__":
    generate_sample_easa_xml()
    generate_sample_manual_pdf()
