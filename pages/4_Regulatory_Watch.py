import streamlit as st
import security
import regulatory_watchdog as watchdog

st.set_page_config(page_title="Regulatory Watch | ReguMap AI", layout="wide")

if "authenticated" not in st.session_state or not st.session_state.authenticated:
    st.warning("Please login on the main page.")
    st.stop()

if not security.check_permission(st.session_state.user_role, "write"):
    st.warning("🛡️ Access Denied. Only Safety Managers can access the Watchtower.")
    st.stop()

st.title("📡 Regulatory Watchtower")
st.caption("EASA RSS Feed Monitoring & Impact Analysis")

alert_tab, task_tab = st.tabs(["🔔 Alert Feed", "📋 Action Center"])

with alert_tab:
    all_alerts = watchdog.get_all_alerts()
    if not all_alerts:
        st.info("No alerts detected yet.")
    else:
        for alert in all_alerts[:20]:
            with st.expander(f"[{alert.get('criticality')}] {alert['title']}"):
                st.markdown(alert.get("summary", ""))
                if st.button("Mark Reviewed", key=f"rev_{alert['feed_id']}"):
                    watchdog.mark_alert_reviewed(alert["feed_id"])
                    st.rerun()

with task_tab:
    st.subheader("📋 Actionable Tasks")
    all_tasks = watchdog.get_all_tasks()
    for task in all_tasks:
        with st.expander(f"{task['rule_id']} → {task['target_manual_section']}"):
            st.markdown(f"**Action:** {task['suggested_change']}")
            if st.button("Mark Implemented", key=f"task_{task['task_id']}"):
                watchdog.mark_task_implemented(task["task_id"])
                st.rerun()
