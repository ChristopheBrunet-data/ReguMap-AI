import os
import streamlit as st
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

import crawler
import regulatory_watchdog as watchdog
import security
import ui_utils
from parser import ManualPdfParser
from engine import ComplianceEngine

# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
HISTORY_DIR = "data/history"
os.makedirs(HISTORY_DIR, exist_ok=True)

st.set_page_config(page_title="ReguMap AI — Agentic GraphRAG", layout="wide", page_icon="✈️")
st.title("✈️ ReguMap AI — Dashboard")
st.caption("Central Hub | Multi-Agent Orchestration | Certifiable Robustness Framework")

# ──────────────────────────────────────────────────────────────────────────────
# SESSION & AUTH
# ──────────────────────────────────────────────────────────────────────────────
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.user_role = None
    st.session_state.user_id = None
    st.session_state.jwt_token = None

def login():
    st.sidebar.title("🔐 Secure Login")
    user = st.sidebar.text_input("User ID")
    pw = st.sidebar.text_input("Password", type="password")
    role = st.sidebar.selectbox("Role (Simulation)", ["AUDITOR", "SAFETY_MANAGER", "ADMIN"])
    
    if st.sidebar.button("Login"):
        st.session_state.authenticated = True
        st.session_state.user_role = role
        st.session_state.user_id = user
        st.session_state.jwt_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.demo-payload" # Mock JWT
        security.log_audit_event(user, "LOGIN")
        st.rerun()

if not st.session_state.authenticated:
    login()
    st.info("Please login to access the ReguMap AI platform.")
    st.stop()

if st.sidebar.button("Logout"):
    security.log_audit_event(st.session_state.user_id, "LOGOUT")
    st.session_state.authenticated = False
    st.rerun()

st.sidebar.divider()
st.sidebar.caption(f"Logged in as: **{st.session_state.user_id}** ({st.session_state.user_role})")

# ──────────────────────────────────────────────────────────────────────────────
# Session State
# ──────────────────────────────────────────────────────────────────────────────
defaults = {
    "engine": None,
    "xml_paths": {},
    "requirements": [],
    "audit_results": [],
    "auto_sync_done": False,
    "chat_history": [],
    "pdf_mapper": None,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ──────────────────────────────────────────────────────────────────────────────
# Autonomous Sync
# ──────────────────────────────────────────────────────────────────────────────
if not st.session_state.auto_sync_done:
    with st.spinner("🔄 Autonomous Sync: Checking EASA database..."):
        crawler.check_for_updates()
        st.session_state.xml_paths = crawler.get_all_xml_paths()
        if st.session_state.xml_paths:
            st.session_state.requirements = ui_utils.load_all_requirements(
                st.session_state.xml_paths, ui_utils.normalize_domain
            )
    st.session_state.auto_sync_done = True

# ──────────────────────────────────────────────────────────────────────────────
# MAIN DASHBOARD
# ──────────────────────────────────────────────────────────────────────────────
st.subheader("🚀 Operational Dashboard")

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Rules Indexed", len(st.session_state.requirements))
with col2:
    st.metric("Manual Chunks", len(st.session_state.engine.manual_chunks) if st.session_state.engine else 0)
with col3:
    st.metric("Audit Findings", len(st.session_state.audit_results))

st.divider()

c_left, c_right = st.columns(2)
with c_left:
    st.markdown("### 📊 Compliance Status")
    if st.session_state.audit_results:
        total = len(st.session_state.audit_results)
        compliant = sum(1 for r in st.session_state.audit_results if r.status.value == "Compliant")
        st.write(f"✅ **Compliant:** {compliant} / {total}")
        st.progress(compliant / total if total > 0 else 0)
    else:
        st.info("No audit data. Navigate to **Compliance Audit** to start.")

with c_right:
    st.markdown("### 📡 Watchtower")
    alerts = watchdog.get_new_alerts_count()
    if alerts > 0:
        st.error(f"🔴 {alerts} new regulatory alerts!")
        if st.button("Open Watchtower"):
            st.switch_page("pages/4_Regulatory_Watch.py")
    else:
        st.success("🟢 Monitoring EASA feeds: No new alerts.")

st.divider()

if st.session_state.engine is None:
    st.header("📥 Upload Operator Manual")
    uploaded_file = st.file_uploader("Upload Manual (PDF)", type=["pdf"])
    if uploaded_file:
        with st.spinner("Parsing & Indexing..."):
            temp_pdf = f"temp_{uploaded_file.name}"
            with open(temp_pdf, "wb") as f:
                f.write(uploaded_file.getbuffer())
            pdf_parser = ManualPdfParser(temp_pdf)
            chunks = list(pdf_parser.parse())
            engine = ComplianceEngine(api_key=GEMINI_API_KEY)
            engine.set_manual_chunks(chunks)
            st.session_state.engine = engine
            st.success("Manual loaded. Proceed to Audit page.")
