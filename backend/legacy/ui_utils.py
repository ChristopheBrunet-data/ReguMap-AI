import os
import json
import io
import streamlit as st
import pandas as pd
from datetime import datetime
from fpdf import FPDF
import requests
from schemas import ComplianceAudit
from parser import EasaXmlParser
from typing import List, Dict, Any

class AeroMindAPIClient:
    """Client HTTP pour l'API AeroMind Compliance (OAS 3.1)"""
    
    def __init__(self, base_url: str = "http://localhost:8000/api/v1"):
        self.base_url = base_url
        # Récupération du JWT depuis la session Streamlit
        self.token = st.session_state.get("jwt_token", "DEMO_TOKEN_CERTIFIABLE")
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}"
        }

    def run_single_audit(self, req_id: str, question: str) -> Dict[str, Any]:
        """Exécute la pipeline multi-agents sur une exigence unique."""
        payload = {
            "requirement_id": req_id,
            "refined_question": question
        }
        response = requests.post(f"{self.base_url}/audit/compliance", json=payload, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def run_batch_audit(self, req_ids: List[str], question: str = "Standard Compliance Check") -> Dict[str, Any]:
        """Exécute un audit en lot (Max 50) - Correction Schéma Appliquée."""
        payload = {
            "requirement_ids": req_ids,
            "refined_question": question
        }
        response = requests.post(f"{self.base_url}/audit/batch", json=payload, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def get_graph_context(self, node_id: str, depth: int = 2) -> Dict[str, Any]:
        """Traverse le graphe Neo4j pour l'explicabilité (XAI)."""
        payload = {
            "node_id": node_id,
            "depth": depth
        }
        response = requests.post(f"{self.base_url}/graph/traverse", json=payload, headers=self.headers)
        response.raise_for_status()
        return response.json()

def load_all_requirements(xml_paths: dict, normalize_domain_func) -> list:
    all_reqs = []
    for domain, path in xml_paths.items():
        if path and os.path.exists(path):
            try:
                parser = EasaXmlParser(path)
                reqs = list(parser.parse())
                for r in reqs:
                    r.domain = normalize_domain_func(r.domain or domain, r.id)
                all_reqs.extend(reqs)
                print(f"DEBUG: ui_utils added {len(reqs)} requirements from {domain}. Total now: {len(all_reqs)}")
            except Exception as e:
                msg = f"Could not parse {domain}: {e}"
                try:
                    st.warning(msg)
                except Exception:
                    print(f"WARNING: {msg}")
    return all_reqs

def save_audit_history(results, history_dir):
    if not results:
        return
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(history_dir, f"audit_{timestamp}.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump([res.model_dump() for res in results], f, indent=2)
    return filepath

def load_audit_history(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [ComplianceAudit(**item) for item in data]

def generate_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Audit Findings")
    return output.getvalue()

def generate_pdf(df, total_checked, non_compliant, partial):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, "Compliance Summary Report", ln=True, align="C")
    pdf.ln(10)
    pdf.set_font("Arial", "I", 10)
    pdf.cell(0, 10, "Certification Notice: This report is generated under the Certifiable Robustness framework and must be validated by a human auditor.", ln=True)
    pdf.ln(5)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, "Executive Summary", ln=True)
    pdf.set_font("Arial", "", 10)
    pdf.cell(0, 8, f"Total Requirements Checked: {total_checked}", ln=True)
    pdf.cell(0, 8, f"Non-Compliant Findings: {non_compliant}", ln=True)
    pdf.cell(0, 8, f"Partial Compliance: {partial}", ln=True)
    pdf.ln(10)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, "Detailed Findings", ln=True)
    pdf.set_font("Arial", "", 10)
    for _, row in df.iterrows():
        pdf.set_font("Arial", "B", 10)
        pdf.cell(0, 8, f"Requirement ID: {row['ERulesId']} - Status: {row['Status']}", ln=True)
        pdf.set_font("Arial", "", 10)
        evidence = str(row["Evidence Quote"]).encode("latin-1", "replace").decode("latin-1")
        pdf.multi_cell(0, 6, f"Evidence: {evidence}")
        if row["Suggested Fix"]:
            fix = str(row["Suggested Fix"]).encode("latin-1", "replace").decode("latin-1")
            pdf.multi_cell(0, 6, f"Suggested Fix: {fix}")
        pdf.ln(5)
    return pdf.output(dest="S").encode("latin-1")

DOMAIN_TAXONOMY = {
    "air-ops": "Air Operations",
    "sera": "SERA (Rules of the Air)",
    "aerodromes": "Aerodromes (Part-ADR)",
    "ground-handling": "Ground Handling",
    "remote-atc": "Remote ATC",
    "initial-airworthiness": "Initial Airworthiness (Part-21)",
    "continuing-airworthiness": "Continuing Airworthiness (Part-M)",
    "additional-airworthiness": "Additional Airworthiness (Part-26)",
    "aircrew": "Aircrew & Licensing",
    "atm-ans": "ATM/ANS",
    "large-rotorcraft": "Large Rotorcraft (CS-29)",
    "info-security": "Information Security",
    "legacy": "Legacy",
}

ID_PREFIX_TO_DOMAIN = {
    "ADR": "Aerodromes (Part-ADR)",
    "CAT": "Air Operations",
    "ORO": "Air Operations",
    "SPA": "Air Operations",
    "NCC": "Air Operations",
    "NCO": "Air Operations",
    "SPO": "Air Operations",
    "SERA": "SERA (Rules of the Air)",
    "ATS": "ATM/ANS",
    "ATM": "ATM/ANS",
    "MET": "ATM/ANS",
    "AIS": "ATM/ANS",
    "FCL": "Aircrew & Licensing",
    "MED": "Aircrew & Licensing",
    "CC": "Aircrew & Licensing",
    "21": "Initial Airworthiness (Part-21)",
    "M": "Continuing Airworthiness (Part-M)",
    "145": "Continuing Airworthiness (Part-M)",
    "26": "Additional Airworthiness (Part-26)",
    "CS": "Large Rotorcraft (CS-29)",
    "IS": "Information Security",
}

def normalize_domain(raw_domain: str, rule_id: str = "") -> str:
    if not raw_domain or raw_domain == "UNKNOWN_DOMAIN":
        prefix = rule_id.split(".")[0] if "." in rule_id else rule_id
        return ID_PREFIX_TO_DOMAIN.get(prefix, "Uncategorized")
    clean = raw_domain.strip().lower()
    return DOMAIN_TAXONOMY.get(clean, raw_domain.strip())
