"""
NLP Relation Extractor — Sprint 2 (Ingestion Avancée).
Uses SpaCy dependency parsing to perform deterministic relationship extraction
between regulatory entities based on sentence grammar.
"""

import re
import logging
import spacy
from spacy.tokens import Doc
from typing import List, Dict, Any, Optional
from ingestion.contracts import RegulatoryEdgeType

logger = logging.getLogger("regumap-ai.nlp-extractor")

# 1. Initialisation SpaCy (Singleton Pattern)
_NLP_MODEL = None

def get_nlp_model():
    """Lazy-loads the SpaCy model to optimize RAM usage."""
    global _NLP_MODEL
    if _NLP_MODEL is None:
        try:
            logger.info("Loading SpaCy model 'en_core_web_sm'...")
            _NLP_MODEL = spacy.load("en_core_web_sm")
        except OSError:
            logger.warning("SpaCy model 'en_core_web_sm' not found. Downloading...")
            from spacy.cli import download
            download("en_core_web_sm")
            _NLP_MODEL = spacy.load("en_core_web_sm")
    return _NLP_MODEL

# 2. Mapping Lexical (Ontologie Juridique)
# Mappe les lemmes de verbes vers notre ontologie stricte (T1.3)
VERB_TO_EDGE_TYPE = {
    # AMENDS: Modification ou remplacement
    "amend": RegulatoryEdgeType.AMENDS,
    "modify": RegulatoryEdgeType.AMENDS,
    "update": RegulatoryEdgeType.AMENDS,
    "replace": RegulatoryEdgeType.AMENDS,
    "supersede": RegulatoryEdgeType.AMENDS,
    
    # IMPLEMENTS: Mise en œuvre ou conformité
    "implement": RegulatoryEdgeType.IMPLEMENTS,
    "comply": RegulatoryEdgeType.IMPLEMENTS,
    "fulfill": RegulatoryEdgeType.IMPLEMENTS,
    "apply": RegulatoryEdgeType.IMPLEMENTS,
    "satisfy": RegulatoryEdgeType.IMPLEMENTS,
    
    # DEFINES: Définition de concepts
    "define": RegulatoryEdgeType.DEFINES,
    "mean": RegulatoryEdgeType.DEFINES,
    "specify": RegulatoryEdgeType.DEFINES,
    "describe": RegulatoryEdgeType.DEFINES,
    
    # CLARIFIES: Explication ou guide (AMC/GM)
    "clarify": RegulatoryEdgeType.CLARIFIES,
    "explain": RegulatoryEdgeType.CLARIFIES,
    "guide": RegulatoryEdgeType.CLARIFIES,
    "illustrate": RegulatoryEdgeType.CLARIFIES,
    "interpret": RegulatoryEdgeType.CLARIFIES,
}

# Regex for EASA Rule IDs (re-used from core_constants for consistency)
EASA_RULE_ID_PATTERN = re.compile(
    r'([A-Z]{2,6}\.[A-Z]{2,5}(?:\.[A-Z]{1,5})?\.\d{3}(?:\.[a-z]\d*)?)'
)

def _find_main_verb(token) -> Optional[str]:
    """
    Remonte l'arbre de dépendances SpaCy pour trouver le verbe d'action 
    liant l'identifiant cité au sujet de la phrase.
    """
    curr = token
    # On remonte vers la racine (ROOT) de la phrase
    while curr.head != curr:
        if curr.pos_ == "VERB":
            return curr.lemma_.lower()
        curr = curr.head
    # Si la racine est elle-même un verbe
    if curr.pos_ == "VERB":
        return curr.lemma_.lower()
    return None

def extract_relations(text: str, source_id: str, entity_index: dict) -> List[Dict[str, Any]]:
    """
    Analyse le texte pour extraire les relations vers d'autres entités réglementaires.
    Utilise la grammaire (SpaCy) pour déterminer la sémantique de l'arête.
    """
    nlp = get_nlp_model()
    doc = nlp(text)
    relations = []
    
    # On itère sur chaque phrase pour une analyse contextuelle précise
    for sent in doc.sents:
        # Recherche des identifiants EASA dans la phrase
        # On utilise une recherche par token pour faciliter le lien avec l'arbre de dépendances
        for token in sent:
            match = EASA_RULE_ID_PATTERN.search(token.text)
            if match:
                target_id = match.group(1).strip().upper()
                
                # Validation O(1) : On ignore si l'entité n'est pas dans notre index (T1.1)
                if target_id not in entity_index or target_id == source_id.upper():
                    continue
                
                # Analyse du verbe principal de la phrase rattaché à cet ID
                verb_lemma = _find_main_verb(token)
                
                # Mapping vers l'ontologie
                edge_type = VERB_TO_EDGE_TYPE.get(verb_lemma, RegulatoryEdgeType.REFERENCES)
                
                # Création de la relation
                relations.append({
                    "source_id": source_id,
                    "target_id": target_id,
                    "edge_type": edge_type,
                    "weight": 0.9,
                    "metadata": {
                        "verb": verb_lemma,
                        "context": sent.text.strip()
                    }
                })
                
    # Déduplication des relations identiques au sein d'un même texte
    unique_relations = {}
    for rel in relations:
        key = (rel["source_id"], rel["target_id"])
        # On garde la relation la plus riche (non-REFERENCE) si doublon
        if key not in unique_relations or rel["edge_type"] != RegulatoryEdgeType.REFERENCES:
            unique_relations[key] = rel
            
    return list(unique_relations.values())
