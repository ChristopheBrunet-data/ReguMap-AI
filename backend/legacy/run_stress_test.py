import os
import json
from dotenv import load_dotenv
from engine import ComplianceEngine
from parser import ManualPdfParser
import ui_utils

def run_stress_test():
    load_dotenv()
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    if not GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY not found in .env")
        return

    print("--- SPRINT 1: SEMANTIC STRESS-TEST ---")
    
    # 1. Load Manual
    manual_path = "OM_A_Stress_Test.pdf"
    print(f"Loading manual: {manual_path}")
    parser = ManualPdfParser(manual_path)
    chunks = list(parser.parse())
    print(f"Parsed {len(chunks)} manual chunks with sliding window.")
    
    # 2. Initialize Engine
    engine = ComplianceEngine(api_key=GEMINI_API_KEY)
    engine.set_manual_chunks(chunks)
    
    # 3. Load Requirements
    xml_paths = {"Operations": "sample_easa.xml"}
    reqs = ui_utils.load_all_requirements(xml_paths, lambda dom, rid: dom)
    print(f"Loaded {len(reqs)} EASA requirements.")
    
    # 4. Build Index
    print("Building hybrid index...")
    engine.build_rule_index(reqs)
    
    # 5. Run Audits
    test_reqs = [r for r in reqs if r.id in ["ORO.FTL.210", "CAT.OP.MPA.150"]]
    
    # Run pre-filtering first
    print("Running semantic pre-filtering...")
    engine.run_semantic_pre_filtering(threshold=0.3)
    print(f"Matched rules: {list(engine.rule_to_chunks.keys())}")
    
    for req in test_reqs:
        print(f"\n[AUDIT] {req.id}...")
        result = engine.evaluate_compliance(req)
        
        print(f"Status: {result.status.value}")
        print(f"Confidence: {result.confidence_score*100:.1f}%")
        
        v_score = f"{result.validation_score*100:.1f}%" if result.validation_score is not None else "N/A"
        print(f"Critic Score: {v_score}")
        
        evidence = result.evidence_quote[:150] + "..." if result.evidence_quote else "No evidence found."
        print(f"Evidence Quote: {evidence}")
        print(f"Source Reference: {result.source_reference}")
        
        if result.status.value == "Compliant":
            print("SUCCESS: Requirement met.")
        elif result.status.value == "Informational":
            print("INFO: No matching manual sections found for this requirement.")
        else:
            print("GAP: Improvement needed.")
            if result.suggested_fix:
                print(f"Suggested Fix: {result.suggested_fix}")

    print("\n--- STRESS-TEST COMPLETE ---")

if __name__ == "__main__":
    run_stress_test()
