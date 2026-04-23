import streamlit as st
import pandas as pd

st.set_page_config(page_title="Knowledge Graph | ReguMap AI", layout="wide")

if "authenticated" not in st.session_state or not st.session_state.authenticated:
    st.warning("Please login on the main page.")
    st.stop()

st.title("🕸️ Knowledge Graph Explorer")

engine = st.session_state.engine
if engine and engine.knowledge_graph.is_built():
    stats = engine.knowledge_graph.get_stats()
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Nodes", stats["total_nodes"])
    c2.metric("Total Edges", stats["total_edges"])
    c3.metric("Node Types", len(stats["nodes_by_type"]))

    st.divider()
    explore_id = st.text_input("Enter a Rule ID to explore (e.g., ORO.GEN.200)")
    if explore_id:
        neighbors = engine.knowledge_graph.get_neighbors_summary(explore_id)
        if neighbors:
            st.success(f"Found {len(neighbors)} connections for **{explore_id}**")
            st.dataframe(pd.DataFrame(neighbors), use_container_width=True)
            
            with st.expander("Multi-hop traversal (depth=2)"):
                traversed = engine.knowledge_graph.traverse(explore_id, depth=2)
                for node in traversed:
                    hop = node.get("hop", 0)
                    prefix = "→ " * hop
                    st.caption(f"{prefix}**[{node.get('node_type', '?')}]** {node['id']} — {node.get('label', '')}")
        else:
            st.warning(f"Rule '{explore_id}' not found.")
else:
    st.info("Knowledge graph not built yet.")
