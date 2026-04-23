"""
Core constants used across the ReguMap-AI application.
"""
import re

# Regex matching EASA rule IDs:
#   3-segment: ORO.GEN.200, ORO.FTL.210, SPA.PBN.100
#   4-segment: ADR.OR.B.005, CAT.OP.MPA.150
#   Optional sub-paragraph: ADR.OR.B.005.a1
EASA_RULE_ID_PATTERN = re.compile(
    r'\b([A-Z]{2,6}\.[A-Z]{2,5}(?:\.[A-Z]{1,5})?\.\d{3}(?:\.[a-z]\d*)?)\b'
)

# Maps domain short codes to full agency names
DOMAIN_TO_AGENCY = {
    "air-ops": "EASA",
    "aerodromes": "EASA",
    "aircrew": "EASA",
    "continuing-airworthiness": "EASA",
    "initial-airworthiness": "EASA",
    "additional-airworthiness": "EASA",
    "atm-ans": "EASA",
    "sera": "EASA",
    "ground-handling": "EASA",
    "remote-atc": "EASA",
    "large-rotorcraft": "EASA",
    "info-security": "EASA",
}
