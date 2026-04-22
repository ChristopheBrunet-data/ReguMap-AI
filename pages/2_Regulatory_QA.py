import streamlit as st
import security
import os

st.set_page_config(page_title="Regulatory Q&A | ReguMap AI", layout="wide")

if "authenticated" not in st.session_state or not st.session_state.authenticated:
    st.warning("Please login on the main page.")
    st.stop()

st.title("💬 Regulatory Q&A")
st.caption("Hybrid RAG (FAISS + BM25 + Knowledge Graph)")

for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

user_question = st.chat_input("Ask a regulatory question...")
if user_question:
    if not st.session_state.engine or not st.session_state.engine.vectorstore:
        st.warning("⚠️ The index has not been built yet. Run an audit to initialize.")
    else:
        try:
            safe_query = security.sanitize_input(user_question)
            with st.spinner("Thinking..."):
                redacted_query = security.redact_pii(safe_query)
                answer = st.session_state.engine.answer_regulatory_question(redacted_query)
                st.session_state.chat_history.append({"role": "user", "content": safe_query})
                st.session_state.chat_history.append({"role": "assistant", "content": answer})
                security.log_audit_event(st.session_state.user_id, "QUERY", safe_query)
                st.rerun()
        except Exception as e:
            st.error(f"Error: {e}")

if st.session_state.chat_history and st.button("🗑️ Clear Chat"):
    st.session_state.chat_history = []
    st.rerun()
