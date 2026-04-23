import os
from dotenv import load_dotenv
import setup_test_data
import crawler
from parser import EasaXmlParser, ManualPdfParser
from engine import ComplianceEngine

def main():
    print("--- ReguMap AI: Local Prototype Initialization ---")
    load_dotenv()
    
    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key:
        print("ERROR: GEMINI_API_KEY is not set in environment or .env file.")
        print("Please set it to your Google AI Studio API key to proceed.")
        return
    
    # 1. Automatically fetch the latest EASA Rules
    print("\nFetching latest EASA Rules via Crawler...")
    xml_path = crawler.fetch_and_extract()
    pdf_path = "sample_manual.pdf"
    
    # If fetch failed or manual is missing, generate dummy data as fallback
    if not xml_path or not os.path.exists(xml_path) or not os.path.exists(pdf_path):
        print("\nRequired data missing. Generating dummy data for fallback...")
        if not xml_path or not os.path.exists(xml_path):
            xml_path = "sample_easa.xml"
            setup_test_data.generate_sample_easa_xml(xml_path)
        if not os.path.exists(pdf_path):
            setup_test_data.generate_sample_manual_pdf(pdf_path)
    
    # 2. Parse Operator Manual
    print("\nParsing PDF...")
    pdf_parser = ManualPdfParser(pdf_path)
    chunks = list(pdf_parser.parse())
    print(f"Extracted {len(chunks)} chunks from PDF.")
    
    # Initialize Engine (FAISS + AI Studio)
    try:
        engine = ComplianceEngine(api_key=gemini_key)
    except Exception as e:
        print(f"Failed to initialize engine: {e}")
        return

    # Initialize FAISS database with chunks
    if chunks:
        # For this prototype we will re-index for simplicity, or it will use existing index
        engine.index_manual_chunks(chunks)

    # 3. Parse EASA Rules and query for "ORO.GEN.200"
    print("\nParsing EASA rules...")
    xml_parser = EasaXmlParser(xml_path)
    requirements = list(xml_parser.parse())
    
    target_req = next((req for req in requirements if req.id == "ORO.GEN.200"), None)
    
    if target_req:
        print(f"\nEvaluating target requirement: {target_req.id}...")
        try:
            audit_result = engine.evaluate_compliance(target_req)
            
            print("\n================== RESULTS ==================")
            print(f"Requirement : {audit_result.requirement_id}")
            print(f"Status      : {audit_result.status}")
            print(f"Evidence    : {audit_result.evidence_quote}")
            print(f"Citation    : {audit_result.source_reference}")
            print(f"Confidence  : {audit_result.confidence_score:.2f}")
            
            if audit_result.confidence_score >= 0.85 and audit_result.status == "Compliant":
                print("\nFINAL ASSESSMENT: [ SUCCESS - COMPLIANT ]")
            elif audit_result.status == "Requires Human Review":
                print("\nFINAL ASSESSMENT: [ FAIL - REQUIRES HUMAN REVIEW ]")
            else:
                print(f"\nFINAL ASSESSMENT: [ {audit_result.status.upper()} ]")
            print("=============================================\n")
            
        except Exception as e:
            print(f"Evaluation failed: {e}")
    else:
        print("Could not find ORO.GEN.200 in the EASA XML.")

if __name__ == "__main__":
    main()
