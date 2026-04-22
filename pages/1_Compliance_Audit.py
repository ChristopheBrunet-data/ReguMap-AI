import streamlit as st
import pandas as pd
import os
from datetime import datetime
import ui_utils
import security
from refiner import QueryRefiner

st.set_page_config(page_title="Compliance Audit | ReguMap AI", layout="wide")

if "authenticated" not in st.session_state or not st.session_state.authenticated:
    st.warning("Please login on the main page.")
    st.stop()

st.title("🔍 Compliance Audit")
st.caption("Dual-View: Regulatory Mapping & Visual Evidence")

# Sidebar - Specific for Audit
with st.sidebar:
    st.header("⚙️ Audit Settings")
    similarity_threshold = st.slider("Similarity Threshold", 0.0, 1.0, 0.5, 0.05)
    limit_audits = st.number_input("Audit Limit", min_value=1, max_value=50, value=3)

# Main UI
col_domain, col_search = st.columns([1, 2])
with col_domain:
    unique_domains = sorted({r.domain for r in st.session_state.requirements if r.domain and r.domain != "Uncategorized"})
    domain_filter = st.multiselect(
        "Filter by Domain(s)", unique_domains, default=unique_domains
    )
with col_search:
    search_query = st.text_input("Search Requirements (e.g., 'ORO.GEN.200', 'SMS')")

filtered_reqs = st.session_state.requirements
if domain_filter:
    filtered_reqs = [r for r in filtered_reqs if r.domain in domain_filter]
if search_query:
    sq = search_query.lower()
    filtered_reqs = [r for r in filtered_reqs if sq in r.id.lower() or sq in r.text.lower()]

if filtered_reqs:
    with st.expander(f"View Filtered Requirements ({len(filtered_reqs)})"):
        req_data = [{
            "ID": r.id, "Domain": r.domain, "Title": r.source_title,
            "Law Type": r.amc_gm_info, "Snippet": r.text[:120] + "..."
        } for r in filtered_reqs]
        st.dataframe(pd.DataFrame(req_data), use_container_width=True)

if st.button("🚀 Run Agentic Compliance Audit", type="primary"):
    if not st.session_state.engine:
        st.error("Upload an Operator Manual PDF on the main page first.")
    elif not st.session_state.requirements:
        st.warning("No EASA requirements loaded.")
    else:
        st.session_state.audit_results = []
        progress_bar = st.progress(0, text="Analyzing intent...")

        GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
        refiner = QueryRefiner(api_key=GEMINI_API_KEY)
        raw_query = search_query if search_query else "General EASA compliance audit"
        refined_data = refiner.refine(raw_query)
        search_keywords = refined_data.get("Search_Keywords", raw_query)
        refined_question = refined_data.get("Refined_Question", raw_query)
        st.info(f"**🧠 Intent:** {refined_question}")

        if not st.session_state.engine.vectorstore:
            with st.spinner("Building hybrid index..."):
                st.session_state.engine.build_rule_index(st.session_state.requirements)

        st.session_state.engine.run_semantic_pre_filtering(threshold=similarity_threshold)

        if search_query and st.session_state.engine.vectorstore:
            scored = st.session_state.engine.hybrid_search(search_keywords, k=limit_audits)
            reqs_to_audit = [r for r, _ in scored]
        else:
            reqs_to_audit = filtered_reqs[:limit_audits]

        for i, req in enumerate(reqs_to_audit):
            res = st.session_state.engine.evaluate_compliance(req, refined_question=refined_question)
            st.session_state.audit_results.append(res)
            progress_bar.progress(30 + int(70 * (i + 1) / len(reqs_to_audit)))
        
        ui_utils.save_audit_history(st.session_state.audit_results, "data/history")
        st.success("Audit Complete!")

# Results Display (Dual-View)
if st.session_state.audit_results:
    total_checked = len(st.session_state.audit_results)
    non_compliant = sum(1 for r in st.session_state.audit_results if r.status.value in ["Gap", "Requires Human Review"])
    partial = sum(1 for r in st.session_state.audit_results if r.status.value == "Partial")

    kpi1, kpi2, kpi3 = st.columns(3)
    kpi1.metric("Total Checked", total_checked)
    kpi2.metric("Non-Compliant", non_compliant)
    kpi3.metric("Partial", partial)

    left_col, right_col = st.columns([3, 2])
    with left_col:
        st.subheader("📊 Results")
        data = [{
            "ERulesId": r.requirement_id, "Status": r.status.value,
            "Evidence Quote": r.evidence_quote, "Citation": r.source_reference,
            "Confidence": f"{r.confidence_score * 100:.1f}%",
            "Suggested Fix": r.suggested_fix or ""
        } for r in st.session_state.audit_results]
        df = pd.DataFrame(data)
        st.dataframe(df, use_container_width=True)

    with right_col:
        st.subheader("🖼️ Evidence")
        mapper = st.session_state.pdf_mapper
        for r in st.session_state.audit_results:
            if mapper:
                crop_path = mapper.save_crop(r.requirement_id)
                if crop_path:
                    st.image(crop_path, caption=f"📄 {r.requirement_id}")
                    continue
            if r.evidence_crop_path and os.path.exists(r.evidence_crop_path):
                st.image(r.evidence_crop_path)
