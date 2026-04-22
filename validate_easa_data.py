import os
from parser import EasaXmlParser

def validate():
    xml_file = "ConsolidatedAerodromeOperatorsPartADR-OR.xml"
    
    if not os.path.exists(xml_file):
        print(f"Error: {xml_file} not found in the current directory.")
        print("Please place the official EASA XML file in the project directory to run validation.")
        return

    print(f"Starting validation for {xml_file}...")
    parser = EasaXmlParser(xml_file)
    
    total_topics = 0
    domains = set()
    
    try:
        for req in parser.parse():
            total_topics += 1
            if req.domain and req.domain != "UNKNOWN_DOMAIN":
                domains.add(req.domain)
                
        print("\n--- Validation Summary ---")
        print(f"Total Topics Extracted : {total_topics}")
        print(f"Unique Domains Found   : {', '.join(domains) if domains else 'None'}")
        print("--------------------------\n")
    except Exception as e:
        print(f"Validation failed during parsing: {e}")

if __name__ == "__main__":
    validate()
