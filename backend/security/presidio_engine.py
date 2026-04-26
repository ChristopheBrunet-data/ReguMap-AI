import logging
from typing import Tuple
from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

logger = logging.getLogger(__name__)

class DataSanitizer:
    """
    Local PII De-identification Engine using Microsoft Presidio.
    Ensures that no sensitive information (Names, Phones, SN) reaches the LLM.
    """
    
    def __init__(self):
        # We use Spacy en_core_web_lg for high-accuracy local extraction
        # This configuration is strict: no external API calls for NLP
        self.analyzer = AnalyzerEngine(default_score_threshold=0.35)
        
        # Add custom recognizer for phone numbers (often missed by default NLP)
        from presidio_analyzer import PatternRecognizer, Pattern
        phone_pattern = Pattern(name="phone_number_pattern", regex=r'\b(\d{3}[-.\s]??\d{3,4}[-.\s]??\d{4}|\d{3}[-.\s]??\d{4})\b', score=0.6)
        phone_recognizer = PatternRecognizer(supported_entity="PHONE_NUMBER", patterns=[phone_pattern])
        self.analyzer.registry.add_recognizer(phone_recognizer)

        # Aviation-specific PII (Sprint 5)
        # Tail Number (Registration): e.g., F-GZCP, N12345
        tail_pattern = Pattern(name="tail_number_pattern", regex=r'\b[A-Z]{1,2}-[A-Z0-9]{1,5}\b|\bN[0-9]{1,5}[A-Z]{0,2}\b', score=0.7)
        tail_recognizer = PatternRecognizer(supported_entity="TAIL_NUMBER", patterns=[tail_pattern])
        self.analyzer.registry.add_recognizer(tail_recognizer)

        # MSN (Manufacturer Serial Number): e.g., MSN 1234, S/N 45678
        msn_pattern = Pattern(name="msn_pattern", regex=r'\b(MSN|S/N|Serial Number)\s*[0-9]{3,5}\b', score=0.7)
        msn_recognizer = PatternRecognizer(supported_entity="MSN", patterns=[msn_pattern])
        self.analyzer.registry.add_recognizer(msn_recognizer)

        # Mandatory PII targets for EASA/DO-326A compliance
        self.anonymizer = AnonymizerEngine()
        self.operators = {
            "PERSON": OperatorConfig("replace", {"new_value": "<PERSON>"}),
            "EMAIL_ADDRESS": OperatorConfig("replace", {"new_value": "<EMAIL>"}),
            "PHONE_NUMBER": OperatorConfig("replace", {"new_value": "<PHONE_NUMBER>"}),
            "LOCATION": OperatorConfig("replace", {"new_value": "<LOCATION>"}),
            "IP_ADDRESS": OperatorConfig("replace", {"new_value": "<IP>"}),
            "TAIL_NUMBER": OperatorConfig("replace", {"new_value": "<TAIL_NUMBER>"}),
            "MSN": OperatorConfig("replace", {"new_value": "<MSN>"}),
            "UK_NHS": OperatorConfig("replace", {"new_value": "<PHONE_NUMBER>"}), # Handle common misidentification
        }

    def sanitize_prompt(self, text: str) -> Tuple[str, str]:
        """
        Detects and masks PII in the given text.
        Returns (anonymized_text, audit_signature).
        """
        if not text.strip():
            return text, "None"

        # 1. Analyze for PII
        results = self.analyzer.analyze(text=text, language='en')
        
        # 2. Anonymize
        anonymized_result = self.anonymizer.anonymize(
            text=text,
            analyzer_results=results,
            operators=self.operators
        )
        
        sanitized_text = anonymized_result.text
        
        # 3. Create Audit Signature (list of unique masked entity types)
        entities_found = sorted(list(set([r.entity_type for r in results])))
        audit_signature = f"Anonymized: {', '.join(entities_found)}" if entities_found else "None"
        
        logger.info(f"Sanitization complete. Signature: {audit_signature}")
        
        return sanitized_text, audit_signature

if __name__ == "__main__":
    # Quick sanity check
    sanitizer = DataSanitizer()
    test_text = "Captain John Doe reported a defect on SN-12345, contact him at 555-0199."
    clean_text, sig = sanitizer.sanitize_prompt(test_text)
    print(f"Original: {test_text}")
    print(f"Cleaned: {clean_text}")
    print(f"Signature: {sig}")
