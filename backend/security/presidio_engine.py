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
        self.analyzer = AnalyzerEngine(default_score_threshold=0.35)
        
        # Add custom recognizer for phone numbers (often missed by default NLP)
        # Supports 3-3-4, 3-4, and international formats
        phone_pattern = Pattern(name="phone_number_pattern", regex=r'\b(\d{3}[-.\s]??\d{3,4}[-.\s]??\d{4}|\d{3}[-.\s]??\d{4})\b', score=0.5)
        phone_recognizer = PatternRecognizer(supported_entity="PHONE_NUMBER", patterns=[phone_pattern])
        self.analyzer.registry.add_recognizer(phone_recognizer)

        self.anonymizer = AnonymizerEngine()
        
        # We can define specific anonymization strategies if needed
        self.operators = {
            "PERSON": OperatorConfig("replace", {"new_value": "<PERSON>"}),
            "PHONE_NUMBER": OperatorConfig("replace", {"new_value": "<PHONE_NUMBER>"}),
            "EMAIL_ADDRESS": OperatorConfig("replace", {"new_value": "<EMAIL>"}),
            "LOCATION": OperatorConfig("replace", {"new_value": "<LOCATION>"}),
            "CRYPTO": OperatorConfig("replace", {"new_value": "<CRYPTO>"}),
            "IBAN_CODE": OperatorConfig("replace", {"new_value": "<IBAN>"}),
            "IP_ADDRESS": OperatorConfig("replace", {"new_value": "<IP>"}),
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
