import os
import json
import io
from datetime import datetime
import streamlit as st
import pandas as pd
from dotenv import load_dotenv
from fpdf import FPDF

import crawler
import setup_test_data
import regulatory_watchdog as watchdog
import security
from parser import EasaXmlParser, ManualPdfParser
from engine import ComplianceEngine
from schemas import ComplianceAudit
from pdf_mapper import PdfMapper

# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
HISTORY_DIR = "data/history"
os.makedirs(HISTORY_DIR, exist_ok=True)

st.set_page_config(page_title="ReguMap AI — Agentic GraphRAG", layout="wide", page_icon="✈️")
st.title("✈️ ReguMap AI — Agentic GraphRAG")
st.caption("Multi-Agent Compliance Board | Hybrid Retrieval | Knowledge Graph | Evidence-First")

# ──────────────────────────────────────────────────────────────────────────────
# SESSION & AUTH
# ──────────────────────────────────────────────────────────────────────────────
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.user_role = None
    st.session_state.user_id = None

def login():
    st.sidebar.title("🔐 Secure Login")
    user = st.sidebar.text_input("User ID")
    pw = st.sidebar.text_input("Password", type="password")
    role = st.sidebar.selectbox("Role (Simulation)", ["AUDITOR", "SAFETY_MANAGER", "ADMIN"])
    
    if st.sidebar.button("Login"):
        # In production, verify pw against hashed hash in DB
        st.session_state.authenticated = True
        st.session_state.user_role = role
        st.session_state.user_id = user
        security.log_audit_event(user, "LOGIN", ip_address=st.context.headers.get("X-Forwarded-For", "127.0.0.1"))
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

# ── Notification Banner ───────────────────────────────────────────────────
new_alert_count = watchdog.get_new_alerts_count()
pending_task_count = watchdog.get_pending_tasks_count()
if new_alert_count > 0 or pending_task_count > 0:
    banner_parts = []
    if new_alert_count > 0:
        banner_parts.append(f"🔴 **{new_alert_count}** new EASA rule(s) detected")
    if pending_task_count > 0:
        banner_parts.append(f"⚠️ **{pending_task_count}** pending compliance task(s)")
    st.warning(" | ".join(banner_parts) + " — Check the **📡 Regulatory Watch** tab.")

# ──────────────────────────────────────────────────────────────────────────────
# Session State
# ──────────────────────────────────────────────────────────────────────────────
defaults = {
    "engine": None,
    "xml_paths": {},
    "xml_path": None,
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
        all_paths = crawler.get_all_xml_paths()
        if all_paths:
            st.session_state.xml_paths = all_paths
            st.session_state.xml_path = next(iter(all_paths.values()))
    # Initialize PDF mapper
    mapper = PdfMapper()
    if not mapper.load():
        pdf_paths = crawler.get_all_pdf_paths()
        if pdf_paths:
            with st.spinner(f"📄 Scanning {len(pdf_paths)} PDFs for rule anchors..."):
                mapper.scan_all_pdfs(pdf_paths)
    st.session_state.pdf_mapper = mapper
    st.session_state.auto_sync_done = True

# ──────────────────────────────────────────────────────────────────────────────
# Domain Taxonomy — maps raw crawler keys & ID prefixes to canonical EASA names
# ──────────────────────────────────────────────────────────────────────────────
DOMAIN_TAXONOMY = {
    # Crawler keys → canonical names
    "air-ops":                  "Air Operations",
    "sera":                     "SERA (Rules of the Air)",
    "aerodromes":               "Aerodromes (Part-ADR)",
    "ground-handling":          "Ground Handling",
    "remote-atc":               "Remote ATC",
    "initial-airworthiness":    "Initial Airworthiness (Part-21)",
    "continuing-airworthiness": "Continuing Airworthiness (Part-M)",
    "additional-airworthiness": "Additional Airworthiness (Part-26)",
    "aircrew":                  "Aircrew & Licensing",
    "atm-ans":                  "ATM/ANS",
    "large-rotorcraft":         "Large Rotorcraft (CS-29)",
    "info-security":            "Information Security",
    "legacy":                   "Legacy",
}

# Rule ID prefix → canonical domain (for auto-tagging from rule IDs)
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
    "CC":  "Aircrew & Licensing",
    "21":  "Initial Airworthiness (Part-21)",
    "M":   "Continuing Airworthiness (Part-M)",
    "145": "Continuing Airworthiness (Part-M)",
    "26":  "Additional Airworthiness (Part-26)",
    "CS":  "Large Rotorcraft (CS-29)",
    "IS":  "Information Security",
}


def normalize_domain(raw_domain: str, rule_id: str = "") -> str:
    """Maps a raw domain string to the canonical EASA taxonomy name."""
    if not raw_domain or raw_domain == "UNKNOWN_DOMAIN":
        # Try to infer from rule ID prefix
        prefix = rule_id.split(".")[0] if "." in rule_id else rule_id
        return ID_PREFIX_TO_DOMAIN.get(prefix, "Uncategorized")
    # Direct lookup from crawler key
    clean = raw_domain.strip().lower()
    return DOMAIN_TAXONOMY.get(clean, raw_domain.strip())


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
def load_all_requirements(xml_paths: dict) -> list:
    all_reqs = []
    for domain, path in xml_paths.items():
        if path and os.path.exists(path):
            try:
                parser = EasaXmlParser(path)
                reqs = list(parser.parse())
                for r in reqs:
                    # Normalize domain at ingestion time
                    r.domain = normalize_domain(r.domain or domain, r.id)
                all_reqs.extend(reqs)
            except Exception as e:
                st.warning(f"Could not parse {domain}: {e}")
    return all_reqs


def save_audit_history(results):
    if not results:
        return
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(HISTORY_DIR, f"audit_{timestamp}.json")
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
    pdf.cell(0, 10, "Disclaimer: This report was generated by AI and requires human validation.", ln=True)
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


# ──────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ──────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("🛠️ Pipeline Status")
    st.subheader("API Status")
    if GEMINI_API_KEY:
        st.success("Gemini API Key: Loaded ✅")
    else:
        st.error("Gemini API Key: Missing ❌")

    st.divider()

    st.subheader("1. EASA Rules Database")
    all_paths = crawler.get_all_xml_paths()
    domain_count = len(all_paths)
    if domain_count > 0:
        st.success(f"✅ {domain_count} domain(s) loaded locally")
        for dom, p in all_paths.items():
            st.caption(f"• {dom}: `{os.path.basename(p)}`")
    else:
        st.warning("⚠️ No EASA XMLs found locally.")

    col_sync1, col_sync2 = st.columns(2)
    with col_sync1:
        if st.button("Sync Current"):
            with st.spinner("Syncing..."):
                crawler.check_for_updates()
                st.session_state.xml_paths = crawler.get_all_xml_paths()
                if st.session_state.xml_paths:
                    st.session_state.xml_path = next(iter(st.session_state.xml_paths.values()))
            st.success("Sync done!")
    with col_sync2:
        if st.button("Sync All Domains"):
            with st.spinner("Crawling all EASA domains…"):
                results = crawler.sync_all_domains()
                st.session_state.xml_paths = results
                if results:
                    st.session_state.xml_path = next(iter(results.values()))
                    st.success(f"Downloaded {len(results)} domain(s)!")
                else:
                    st.error("No domains downloaded.")

    if st.session_state.xml_paths and not st.session_state.requirements:
        with st.spinner("Loading EASA requirements from all domains..."):
            st.session_state.requirements = load_all_requirements(st.session_state.xml_paths)
        if st.session_state.requirements:
            st.success(f"✅ {len(st.session_state.requirements)} rules loaded.")

    st.divider()
    st.subheader("2. Operator Manual")
    uploaded_file = st.file_uploader("Upload Manual (PDF)", type=["pdf"])
    if uploaded_file is not None and st.session_state.engine is None:
        if not GEMINI_API_KEY:
            st.error("Missing GEMINI_API_KEY.")
        else:
            with st.spinner("Parsing PDF & initializing engine..."):
                temp_pdf = f"temp_{uploaded_file.name}"
                with open(temp_pdf, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                pdf_parser = ManualPdfParser(temp_pdf)
                chunks = list(pdf_parser.parse())
                engine = ComplianceEngine(api_key=GEMINI_API_KEY)
                engine.set_manual_chunks(chunks)
                st.session_state.engine = engine
                st.success(f"✅ {len(chunks)} manual sections loaded.")

    st.divider()
    st.header("⚙️ Engine Settings")
    similarity_threshold = st.slider("Similarity Threshold", 0.0, 1.0, 0.5, 0.05)

    st.divider()
    st.header("📂 Audit History")
    history_files = sorted(
        [f for f in os.listdir(HISTORY_DIR) if f.endswith(".json")], reverse=True
    ) if os.path.exists(HISTORY_DIR) else []
    if history_files:
        selected_history = st.selectbox("Load Previous Audit", ["-- Select --"] + history_files)
        if selected_history != "-- Select --" and st.button("Load History"):
            st.session_state.audit_results = load_audit_history(os.path.join(HISTORY_DIR, selected_history))
            st.success("History loaded.")
    else:
        st.info("No audit history yet.")

# ──────────────────────────────────────────────────────────────────────────────
# MAIN PANEL — 4 Tabs
# ──────────────────────────────────────────────────────────────────────────────
tab_audit, tab_chat, tab_graph, tab_board, tab_watch = st.tabs([
    "🔍 Compliance Audit", "💬 Regulatory Q&A", "🕸️ Knowledge Graph", "📊 Agent Board", "📡 Regulatory Watch"
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1: Compliance Audit — Dual-View (Status + Visual Evidence)
# ══════════════════════════════════════════════════════════════════════════════
with tab_audit:
    col_domain, col_search, col_limit = st.columns([1, 2, 1])
    with col_domain:
        unique_domains = sorted({r.domain for r in st.session_state.requirements if r.domain and r.domain != "Uncategorized"})
        domain_filter = st.multiselect(
            "Filter by Domain(s)", unique_domains, default=unique_domains,
            help="Select one or more EASA domains. Empty = All."
        )
    with col_search:
        search_query = st.text_input("Search Requirements (e.g., 'ORO.GEN.200', 'SMS')")
    with col_limit:
        limit_audits = st.number_input("Audit Limit", min_value=1, max_value=50, value=3)

    filtered_reqs = st.session_state.requirements
    if domain_filter:
        filtered_reqs = [r for r in filtered_reqs if r.domain in domain_filter]
    if search_query:
        sq = search_query.lower()
        filtered_reqs = [r for r in filtered_reqs if sq in r.id.lower() or sq in r.text.lower()]

    if filtered_reqs:
        st.subheader(f"📋 EASA Requirements ({len(filtered_reqs)} rules)")
        with st.expander("View Filtered Requirements", expanded=False):
            req_data = [{
                "ID": r.id, "Domain": r.domain, "Title": r.source_title,
                "Law Type": r.amc_gm_info, "Snippet": r.text[:120] + "..." if len(r.text) > 120 else r.text
            } for r in filtered_reqs]
            st.dataframe(pd.DataFrame(req_data), use_container_width=True)

    if st.button("🚀 Run Agentic Compliance Audit", type="primary"):
        if not st.session_state.xml_paths and not st.session_state.xml_path:
            st.error("No EASA XML detected. Click 'Sync All Domains'.")
        elif not st.session_state.engine:
            st.error("Upload an Operator Manual PDF first.")
        elif not st.session_state.requirements:
            st.warning("No EASA requirements loaded.")
        else:
            st.session_state.audit_results = []
            progress_bar = st.progress(0, text="Analyzing intent...")

            from refiner import QueryRefiner
            refiner = QueryRefiner(api_key=GEMINI_API_KEY)
            raw_query = search_query if search_query else "General EASA compliance audit"
            refined_data = refiner.refine(raw_query)
            search_keywords = refined_data.get("Search_Keywords", raw_query)
            refined_question = refined_data.get("Refined_Question", raw_query)
            st.info(f"**🧠 Intent:** {refined_question}  \n*Keywords: {search_keywords}*")

            progress_bar.progress(10, text="Building hybrid index (FAISS + BM25 + Graph)...")
            if not st.session_state.engine.vectorstore:
                with st.spinner(f"Building hybrid index for {len(st.session_state.requirements)} rules..."):
                    st.session_state.engine.build_rule_index(st.session_state.requirements)

            progress_bar.progress(20, text="Semantic pre-filtering...")
            st.session_state.engine.run_semantic_pre_filtering(threshold=similarity_threshold)

            if search_query and st.session_state.engine.vectorstore:
                scored = st.session_state.engine.hybrid_search(search_keywords, k=limit_audits)
                reqs_to_audit = [r for r, _ in scored]
            else:
                reqs_to_audit = filtered_reqs[:limit_audits]

            if not reqs_to_audit:
                st.warning("No matching rules found.")
            else:
                progress_bar.progress(30, text="4-Agent Compliance Board running...")
                for i, req in enumerate(reqs_to_audit):
                    try:
                        res = st.session_state.engine.evaluate_compliance(req, refined_question=refined_question)
                        st.session_state.audit_results.append(res)
                    except Exception as e:
                        st.error(f"Failed on {req.id}: {e}")
                    progress_bar.progress(30 + int(70 * (i + 1) / len(reqs_to_audit)))
                save_audit_history(st.session_state.audit_results)
                st.success("✅ Agentic Audit Complete & Saved!")

    # ── Dual-View Results ─────────────────────────────────────────────────
    if st.session_state.audit_results:
        total_checked = len(st.session_state.audit_results)
        non_compliant = sum(1 for r in st.session_state.audit_results if r.status in ["Gap", "Requires Human Review"])
        partial = sum(1 for r in st.session_state.audit_results if r.status == "Partial")

        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
        kpi1.metric("Total Checked", total_checked)
        kpi2.metric("Non-Compliant", non_compliant, delta_color="inverse")
        kpi3.metric("Partial", partial, delta_color="off")
        avg_val = sum(r.validation_score or 0 for r in st.session_state.audit_results) / max(total_checked, 1)
        kpi4.metric("Avg Critic Score", f"{avg_val:.2f}")

        # Dual-view: left = status table + clickable rules, right = evidence
        left_col, right_col = st.columns([3, 2])

        with left_col:
            st.subheader("📊 Compliance Status")
            data = [{
                "ERulesId": r.requirement_id, "Status": r.status,
                "Evidence Quote": r.evidence_quote, "Citation": r.source_reference,
                "Confidence": f"{r.confidence_score * 100:.1f}%",
                "Critic Score": f"{(r.validation_score or 0) * 100:.0f}%",
                "Suggested Fix": r.suggested_fix or ""
            } for r in st.session_state.audit_results]
            df = pd.DataFrame(data)

            def color_status(val):
                color = "green" if val == "Compliant" else "red" if val == "Gap" else "orange"
                return f"background-color: {color}"

            st.dataframe(df.style.map(color_status, subset=["Status"]), use_container_width=True)

            # Clickable Rule IDs — open PDF Window View
            mapper = st.session_state.pdf_mapper
            if mapper and mapper.index:
                st.caption("📄 **Click a Rule ID to view its location in the official EASA PDF:**")
                rule_cols = st.columns(min(len(st.session_state.audit_results), 5))
                for i, r in enumerate(st.session_state.audit_results):
                    col_idx = i % min(len(st.session_state.audit_results), 5)
                    entry = mapper.get_entry(r.requirement_id)
                    if entry:
                        with rule_cols[col_idx]:
                            if st.button(f"📄 {r.requirement_id}", key=f"pdf_btn_{r.requirement_id}",
                                         help=f"Page {entry['page']} in {entry['domain']} PDF"):
                                st.session_state["_pdf_view_rule"] = r.requirement_id
                    else:
                        with rule_cols[col_idx]:
                            st.button(f"⚠️ {r.requirement_id}", key=f"pdf_btn_{r.requirement_id}",
                                      disabled=True, help="No PDF anchor found")

        with right_col:
            st.subheader("🖼️ Visual Evidence")
            mapper = st.session_state.pdf_mapper

            for r in st.session_state.audit_results:
                # Priority 1: PDF crop from mapper
                if mapper:
                    crop_path = mapper.save_crop(r.requirement_id)
                    if crop_path:
                        st.image(crop_path, caption=f"📄 {r.requirement_id} — PDF Page {mapper.get_page(r.requirement_id)}")
                        continue

                # Priority 2: Manual evidence crop
                if r.evidence_crop_path and os.path.exists(r.evidence_crop_path):
                    st.image(r.evidence_crop_path, caption=f"{r.requirement_id}: {r.source_reference}")
                else:
                    st.caption(f"{r.requirement_id}: No visual evidence available")

        # ── PDF Window View Dialog ────────────────────────────────────────
        if "_pdf_view_rule" in st.session_state and st.session_state["_pdf_view_rule"]:
            rule_to_view = st.session_state["_pdf_view_rule"]
            st.session_state["_pdf_view_rule"] = None  # Reset

            mapper = st.session_state.pdf_mapper
            entry = mapper.get_entry(rule_to_view) if mapper else None

            if entry:
                st.divider()
                st.subheader(f"📖 PDF Window View — {rule_to_view}")
                st.caption(f"**Domain:** {entry['domain']} | **Page:** {entry['page']} | **PDF:** `{os.path.basename(entry['pdf_path'])}`")

                view_tab1, view_tab2 = st.tabs(["🔍 Rule Crop (Highlighted)", "📄 Full Page"])

                with view_tab1:
                    crop_data = mapper.get_page_crop(rule_to_view, zoom=2.5)
                    if crop_data:
                        st.image(crop_data, caption=f"{rule_to_view} — Cropped from PDF page {entry['page']}", use_container_width=True)
                    else:
                        st.warning("Could not generate crop for this rule.")

                with view_tab2:
                    full_page = mapper.render_full_page(rule_to_view, zoom=1.5)
                    if full_page:
                        st.image(full_page, caption=f"Full page {entry['page']} — {entry['domain']}", use_container_width=True)
                    else:
                        st.warning("Could not render full page.")

        st.subheader("📥 Export")
        c1, c2 = st.columns(2)
        with c1:
            st.download_button("📊 Excel", generate_excel(df),
                               f"audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        with c2:
            st.download_button("📄 PDF", generate_pdf(df, total_checked, non_compliant, partial),
                               f"compliance_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf", "application/pdf")

        st.divider()
        st.subheader("🛠️ Remediation Plans")
        for _, row in df.iterrows():
            if row["Status"] in ["Gap", "Partial", "Requires Human Review"]:
                with st.expander(f"Fix for {row['ERulesId']} ({row['Status']})"):
                    st.write(f"**Suggested Fix:** {row['Suggested Fix']}" if row["Suggested Fix"] else "No fix suggested.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: Regulatory Q&A Chat
# ══════════════════════════════════════════════════════════════════════════════
with tab_chat:
    st.subheader("💬 Ask Your EASA Regulatory Expert")
    st.caption("Powered by hybrid retrieval (FAISS + BM25 + Graph) with cross-encoder re-ranking.")

    chat_unique_domains = sorted({r.domain for r in st.session_state.requirements if r.domain and r.domain != "Uncategorized"})
    chat_domain_filter = st.multiselect(
        "Scope by Domain(s)", chat_unique_domains, default=[],
        help="Leave empty for All domains.", key="chat_domain"
    )

    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    user_question = st.chat_input("Ask a regulatory question...")
    if user_question:
        if not st.session_state.engine or not st.session_state.engine.vectorstore:
            st.warning("⚠️ Run a Compliance Audit first to build the index.")
        elif not GEMINI_API_KEY:
            st.error("Missing GEMINI_API_KEY.")
        else:
            if st.button("💬 Ask Gemini", type="primary"):
                try:
                    # 🔐 LLM GUARDRAIL: Sanitize input for Prompt Injection
                    safe_query = security.sanitize_input(user_question)
                    
                    with st.spinner("Analyzing EASA Knowledge Graph..."):
                        # 🔐 PII REDACTION: Mask sensitive info before sending to cloud
                        redacted_query = security.redact_pii(safe_query)
                        
                        domain_arg = chat_domain_filter[0] if len(chat_domain_filter) == 1 else None
                        answer = st.session_state.engine.answer_regulatory_question(
                            redacted_query, domain_filter=domain_arg
                        )
                        st.session_state.chat_history.append({"role": "user", "content": safe_query})
                        st.session_state.chat_history.append({"role": "assistant", "content": answer})
                        
                        security.log_audit_event(st.session_state.user_id, "QUERY", safe_query)
                except security.SecurityException as se:
                    st.error(f"🛡️ Security Block: {str(se)}")
                except Exception as e:
                    st.error(f"Error: {e}")

    if st.session_state.chat_history and st.button("🗑️ Clear Chat"):
        st.session_state.chat_history = []
        st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3: Knowledge Graph Explorer
# ══════════════════════════════════════════════════════════════════════════════
with tab_graph:
    st.subheader("🕸️ Regulatory Knowledge Graph")

    engine = st.session_state.engine
    if engine and engine.knowledge_graph.is_built():
        stats = engine.knowledge_graph.get_stats()
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Nodes", stats["total_nodes"])
        c2.metric("Total Edges", stats["total_edges"])
        c3.metric("Node Types", len(stats["nodes_by_type"]))

        col_nodes, col_edges = st.columns(2)
        with col_nodes:
            st.caption("**Nodes by Type**")
            st.json(stats["nodes_by_type"])
        with col_edges:
            st.caption("**Edges by Type**")
            st.json(stats["edges_by_type"])

        st.divider()
        st.subheader("🔎 Rule Explorer")
        explore_id = st.text_input("Enter a Rule ID to explore (e.g., ORO.GEN.200)", key="graph_explore")
        if explore_id:
            neighbors = engine.knowledge_graph.get_neighbors_summary(explore_id)
            if neighbors:
                st.success(f"Found {len(neighbors)} connections for **{explore_id}**")
                neighbor_df = pd.DataFrame(neighbors)
                st.dataframe(neighbor_df, use_container_width=True)

                with st.expander("Multi-hop traversal (depth=2)"):
                    traversed = engine.knowledge_graph.traverse(explore_id, depth=2)
                    for node in traversed:
                        hop = node.get("hop", 0)
                        prefix = "→ " * hop
                        nt = node.get("node_type", "?")
                        st.caption(f"{prefix}**[{nt}]** {node['id']} — {node.get('label', '')}")
            else:
                st.warning(f"Rule '{explore_id}' not found in the graph.")

        st.divider()
        st.subheader("⚠️ Conflict Detector")
        conflict_id = st.text_input("Check conflicts for Rule ID", key="conflict_check")
        if conflict_id:
            conflicts = engine.knowledge_graph.find_conflicts(conflict_id)
            if conflicts:
                st.error(f"Found {len(conflicts)} conflict(s)!")
                st.json(conflicts)
            else:
                st.success("No conflicts detected for this rule.")
    else:
        st.info("Knowledge graph not built yet. Run a Compliance Audit to initialize.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 4: Agent Board
# ══════════════════════════════════════════════════════════════════════════════
with tab_board:
    st.subheader("📊 Agent Board — Compliance Pipeline Trace")
    st.caption("Each audit finding passes through 4 agents: Researcher → Conflict Detector → Auditor → Critic")

    if st.session_state.audit_results:
        for r in st.session_state.audit_results:
            status_icon = "✅" if r.status == "Compliant" else "❌" if r.status == "Gap" else "⚠️"
            with st.expander(f"{status_icon} {r.requirement_id} — {r.status} (Critic: {(r.validation_score or 0)*100:.0f}%)"):
                st.markdown(f"**Evidence:** {r.evidence_quote}")
                st.markdown(f"**Citation:** {r.source_reference}")
                st.markdown(f"**Confidence:** {r.confidence_score*100:.1f}%")
                if r.cross_refs_used:
                    st.markdown(f"**Cross-Refs Used:** {', '.join(r.cross_refs_used)}")
                if r.agent_trace:
                    st.divider()
                    st.markdown("**🔗 Agent Pipeline Trace:**")
                    for step in r.agent_trace.split(" → "):
                        st.caption(f"  → {step}")
                if r.suggested_fix:
                    st.info(f"💡 **Fix:** {r.suggested_fix}")
    else:
        st.info("No audit results yet. Run a Compliance Audit to see agent traces.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 5: Regulatory Watch & Prevention
# ══════════════════════════════════════════════════════════════════════════════
with tab_watch:
    # 🔐 RBAC: Only SAFETY_MANAGER or ADMIN can access the Watchtower
    if not security.check_permission(st.session_state.user_role, "write"):
        st.warning("🛡️ Access Denied. Only Safety Managers can access the Watchtower.")
    else:
        st.subheader("📡 Regulatory Watch & Prevention")
    alert_tab, task_tab = st.tabs(["🔔 Alert Feed", "📋 Action Center"])

    with alert_tab:
        all_alerts = watchdog.get_all_alerts()
        if not all_alerts:
            st.info("No alerts yet. Click **Scan EASA Feeds Now** to start monitoring.")
        else:
            # Filter controls
            fcol1, fcol2 = st.columns(2)
            with fcol1:
                crit_filter = st.multiselect(
                    "Filter by Criticality", ["HIGH", "MEDIUM", "LOW"],
                    default=["HIGH", "MEDIUM"], key="watch_crit_filter"
                )
            with fcol2:
                status_filter = st.multiselect(
                    "Filter by Status", ["new", "reviewed", "archived"],
                    default=["new", "reviewed"], key="watch_status_filter"
                )

            filtered_alerts = [
                a for a in all_alerts
                if a.get("criticality") in crit_filter and a.get("status") in status_filter
            ]

            for alert in filtered_alerts[:25]:
                crit = alert.get("criticality", "LOW")
                crit_emoji = "🔴" if crit == "HIGH" else "🟡" if crit == "MEDIUM" else "🟢"
                status_badge = "🆕" if alert["status"] == "new" else "✅" if alert["status"] == "reviewed" else "📦"

                with st.expander(
                    f"{crit_emoji} {status_badge} [{crit}] {alert['title'][:100]}",
                    expanded=(alert["status"] == "new")
                ):
                    st.caption(f"**Source:** {alert.get('feed_source', '?')} | **Published:** {alert.get('published', '?')} | **Detected:** {alert.get('detected_at', '?')[:19]}")
                    st.markdown(alert.get("summary", "No summary."))

                    if alert.get("rule_ids"):
                        st.markdown(f"**Referenced Rules:** {', '.join(alert['rule_ids'])}")

                    if alert.get("link"):
                        st.markdown(f"[📎 View on EASA website]({alert['link']})")

                    # Impact Analysis
                    impact = alert.get("impact_analysis")
                    if impact and not impact.get("error"):
                        st.divider()
                        conflict_color = "red" if impact["conflict_level"] == "HIGH" else "orange" if impact["conflict_level"] == "MEDIUM" else "green"
                        st.markdown(f"**Impact Level:** :{conflict_color}[{impact['conflict_level']}]")
                        st.markdown(f"**Summary:** {impact.get('summary', 'N/A')}")

                        if impact.get("affected_sections"):
                            st.markdown("**Affected Manual Sections:**")
                            for sec in impact["affected_sections"]:
                                st.caption(f"  📄 Page {sec['page']}, {sec['section']}")

                        if impact.get("related_rules"):
                            st.markdown("**Related EASA Rules:**")
                            for rr in impact["related_rules"]:
                                st.caption(f"  → [{rr['id']}] {rr['title']} (score: {rr['score']})")

                    # Action buttons
                    bcol1, bcol2, bcol3 = st.columns(3)
                    with bcol1:
                        if alert["status"] == "new" and st.button("✅ Mark Reviewed", key=f"rev_{alert['feed_id'][:20]}"):
                            watchdog.mark_alert_reviewed(alert["feed_id"])
                            st.rerun()
                    with bcol2:
                        if alert["status"] != "archived" and st.button("📦 Archive", key=f"arch_{alert['feed_id'][:20]}"):
                            watchdog.archive_alert(alert["feed_id"])
                            st.rerun()
                    with bcol3:
                        if not impact and st.session_state.engine:
                            if st.button("🔍 Run Impact Analysis", key=f"impact_{alert['feed_id'][:20]}"):
                                with st.spinner("Analyzing impact..."):
                                    result = watchdog.run_impact_analysis(alert, st.session_state.engine)
                                    watchdog.update_alert_impact(alert["feed_id"], result)
                                st.rerun()

    with task_tab:
        st.subheader("📋 Compliance Tasks — Action Center")
        all_tasks = watchdog.get_all_tasks()

        if not all_tasks:
            st.info("No compliance tasks yet. Tasks are auto-generated when impact analysis finds affected manual sections.")
        else:
            # Status filter
            task_status_filter = st.multiselect(
                "Filter by Status", ["Pending", "In Progress", "Implemented", "Archived"],
                default=["Pending", "In Progress"], key="task_status_filter"
            )
            filtered_tasks = [t for t in all_tasks if t.get("status") in task_status_filter]

            for task in filtered_tasks:
                crit = task.get("criticality", "LOW")
                crit_emoji = "🔴" if crit == "HIGH" else "🟡" if crit == "MEDIUM" else "🟢"
                status = task.get("status", "Pending")
                status_emoji = "⏳" if status == "Pending" else "🔧" if status == "In Progress" else "✅" if status == "Implemented" else "📦"

                with st.expander(f"{crit_emoji} {status_emoji} [{status}] {task['rule_id']} → {task['target_manual_section']}"):
                    st.markdown(f"**Task ID:** `{task['task_id']}`")
                    st.markdown(f"**Rule:** {task['rule_id']}")
                    st.markdown(f"**Target:** {task['target_manual_section']}")
                    st.markdown(f"**Action:** {task['suggested_change']}")
                    st.caption(f"Created: {task.get('created_at', '?')[:19]}")

                    if task.get("implemented_at"):
                        st.success(f"Implemented on: {task['implemented_at'][:19]}")

                    tcol1, tcol2 = st.columns(2)
                    with tcol1:
                        if status == "Pending" and st.button("🔧 Start", key=f"start_{task['task_id']}"):
                            watchdog.mark_task_in_progress(task["task_id"])
                            st.rerun()
                    with tcol2:
                        if status in ["Pending", "In Progress"] and st.button("✅ Mark Implemented", key=f"done_{task['task_id']}"):
                            watchdog.mark_task_implemented(task["task_id"])
                            st.rerun()
