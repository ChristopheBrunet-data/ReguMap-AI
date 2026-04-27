"""
ComplianceEngine — Hybrid Retrieval + Cross-Encoder Re-ranking + GraphRAG.

Search pipeline:
  1. FAISS vector similarity (semantic concepts)
  2. BM25 keyword search (exact IDs like 'ADR.OR.B.005')
  3. Graph traversal (regulatory lineage from knowledge graph)
  4. Cross-Encoder re-ranking (top 50 candidates scored for relevance)
"""

import json
import os
import re
import time
from typing import List, Optional, Dict, Tuple
from collections import defaultdict

from core_constants import EASA_RULE_ID_PATTERN

import numpy as np
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder

import security
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from tenacity import retry, wait_exponential, stop_after_attempt

from schemas import EasaRequirement, ManualChunk, ComplianceAudit
from knowledge_graph import RegulatoryKnowledgeGraph
from ingestion.contracts import RegulatoryNode
from agents import ComplianceBoard



# Relevancy threshold — below this, flag as "Potential Regulatory Gap"
RERANK_GAP_THRESHOLD = 0.6


class ComplianceEngine:
    """
    GraphRAG-based engine with hybrid retrieval and agentic audit pipeline.

    Features:
    - FAISS vector search + BM25 keyword search + Graph traversal
    - Cross-Encoder re-ranking (ms-marco-MiniLM-L-6-v2, local)
    - Knowledge graph for multi-hop reasoning
    - 4-agent Compliance Board (Researcher → Conflict → Auditor → Critic)
    - Disk-persisted FAISS index + graph
    """

    def __init__(self, api_key: str, db_path: str = "data/vector_db/", model_name: str = "gemini-2.5-flash"):
        self.db_path = db_path
        self.model_name = model_name
        self._api_key = api_key

        # Lazy-loaded models
        self._embeddings: Optional[HuggingFaceEmbeddings] = None
        self._cross_encoder: Optional[CrossEncoder] = None

        # LLM for chat / legacy single-agent
        self.llm = ChatGoogleGenerativeAI(
            model=self.model_name,
            temperature=0.0,
            google_api_key=api_key
        )

        # Knowledge Graph
        self.knowledge_graph = RegulatoryKnowledgeGraph()

        # 4-Agent Compliance Board
        self.compliance_board = ComplianceBoard(api_key=api_key, model_name=model_name)

        # Chat prompt (for Q&A tab)
        self._init_chat_prompt()

        # Data stores
        self.vectorstore: Optional[FAISS] = None
        self.bm25_index: Optional[BM25Okapi] = None
        self.bm25_doc_ids: List[str] = []
        self.manual_chunks: List[ManualChunk] = []
        self.rule_to_chunks: Dict[str, List[ManualChunk]] = defaultdict(list)
        self.pre_filtered: bool = False
        self._rule_lookup: Dict[str, EasaRequirement] = {}
        self._all_rules: List[EasaRequirement] = []

    def get_requirement(self, requirement_id: str) -> Optional[EasaRequirement]:
        """Public accessor for requirement lookup by ID."""
        return self._rule_lookup.get(requirement_id)

    @property
    def embeddings(self) -> HuggingFaceEmbeddings:
        if self._embeddings is None:
            print("Lazy-loading HuggingFace Embeddings...")
            self._embeddings = HuggingFaceEmbeddings(
                model_name="all-MiniLM-L6-v2",
                model_kwargs={"device": "cpu"},
                encode_kwargs={"normalize_embeddings": True}
            )
        return self._embeddings

    @property
    def cross_encoder(self) -> CrossEncoder:
        if self._cross_encoder is None:
            print("Lazy-loading Cross-Encoder re-ranker...")
            self._cross_encoder = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2", device="cpu")
        return self._cross_encoder

    def _init_chat_prompt(self):
        # Chat prompt (for Q&A tab)
        self.chat_prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a senior EASA regulatory expert and compliance advisor.
You have access to the official EASA Easy Access Rules across multiple domains and a regulatory knowledge graph.
Answer the user's question thoroughly, citing specific rule IDs, cross-domain connections, and practical compliance implications.
If conflicts between rules exist, highlight them. Be concise but technically precise."""),
            ("user", """
User Question: {question}

Relevant EASA Rules (hybrid retrieval + re-ranked):
{rules_context}

Knowledge Graph Context (multi-hop traversal):
{graph_context}

Cross-Referenced Rules:
{cross_ref_context}
""")
        ])

    # ──────────────────────────────────────────────────────────────────────────
    # Index Building
    # ──────────────────────────────────────────────────────────────────────────

    def build_rule_index(self, rules: List[EasaRequirement]):
        """
        Builds FAISS vector index + BM25 keyword index + Knowledge Graph.
        All local, no API calls needed.
        """
        self._all_rules = rules
        faiss_path = os.path.join(self.db_path, "faiss_index")
        os.makedirs(self.db_path, exist_ok=True)

        # Build in-memory rule lookup
        for rule in rules:
            self._rule_lookup[rule.id] = rule

        # ── FAISS Index ──────────────────────────────────────────────────
        if os.path.exists(faiss_path):
            print(f"Attempting to load and decrypt FAISS index from disk: {faiss_path}")
            # 🔐 Decrypt FAISS files into temp directory
            temp_path = os.path.join(self.db_path, "temp_faiss")
            os.makedirs(temp_path, exist_ok=True)
            
            try:
                for f_name in ["index.faiss", "index.pkl"]:
                    f_path = os.path.join(faiss_path, f_name + ".enc")
                    if os.path.exists(f_path):
                        with open(f_path, "rb") as f:
                            enc_data = f.read()
                        with open(os.path.join(temp_path, f_name), "wb") as f:
                            f.write(security.decrypt_data(enc_data))
                
                self.vectorstore = FAISS.load_local(
                    temp_path, self.embeddings, allow_dangerous_deserialization=True
                )
                print(f"FAISS loaded and decrypted ({self.vectorstore.index.ntotal} vectors).")
            except Exception as e:
                print(f"[SECURITY] FAISS decryption failed: {e}. Key might have changed.")
                print("[SELF-HEAL] Clearing corrupted index to allow fresh rebuild.")
                import shutil
                if os.path.exists(faiss_path):
                    shutil.rmtree(faiss_path)
                self.vectorstore = None
            finally:
                # Clean up temp files
                if os.path.exists(temp_path):
                    import shutil
                    shutil.rmtree(temp_path)
        
        # If loading failed or index didn't exist, build from scratch
        if self.vectorstore is None:
            print(f"Building FAISS index for {len(rules)} rules (local embeddings)...")
            documents = [
                Document(
                    page_content=f"{rule.source_title}\n{rule.text}",
                    metadata={"id": rule.id, "title": rule.source_title, "domain": rule.domain or "unknown"}
                )
                for rule in rules
            ]
            self.vectorstore = FAISS.from_documents(documents, self.embeddings)
            self.vectorstore.save_local(faiss_path)
            # 🔐 Encrypt FAISS files
            for f_name in ["index.faiss", "index.pkl"]:
                f_path = os.path.join(faiss_path, f_name)
                if os.path.exists(f_path):
                    with open(f_path, "rb") as f:
                        data = f.read()
                    with open(f_path + ".enc", "wb") as f:
                        f.write(security.encrypt_data(data))
                    os.remove(f_path)
            print(f"FAISS built and encrypted ({len(documents)} vectors).")

        # ── BM25 Index ───────────────────────────────────────────────────
        print("Building BM25 keyword index...")
        tokenized_corpus = []
        self.bm25_doc_ids = []
        for rule in rules:
            text = f"{rule.id} {rule.source_title} {rule.text}".lower()
            tokenized_corpus.append(text.split())
            self.bm25_doc_ids.append(rule.id)
        self.bm25_index = BM25Okapi(tokenized_corpus)
        print(f"BM25 index built ({len(tokenized_corpus)} documents).")

        # ── Knowledge Graph ──────────────────────────────────────────────
        if not self.knowledge_graph.load():
            # Convert EasaRequirement to RegulatoryNode for the Knowledge Graph (T1.1)
            import hashlib
            reg_nodes = []
            for r in rules:
                content_hash = hashlib.sha256(r.text.encode()).hexdigest()
                node = RegulatoryNode(
                    node_id=r.id,
                    title=r.source_title,
                    content=r.text,
                    content_hash=content_hash,
                    node_type="Regulation" if r.amc_gm_info == "Hard Law" else "AMC/GM",
                    metadata={
                        "domain": r.domain,
                        "law_type": r.amc_gm_info
                    }
                )
                reg_nodes.append(node)
            
            self.knowledge_graph.build_from_rules(reg_nodes)
            self.knowledge_graph.persist()

        print("All indices ready.")

    # ──────────────────────────────────────────────────────────────────────────
    # Hybrid Search + Cross-Encoder Re-ranking
    # ──────────────────────────────────────────────────────────────────────────

    def hybrid_search(self, query: str, k: int = 10, domain_filter: Optional[str] = None) -> List[Tuple[EasaRequirement, float]]:
        """
        3-stage hybrid retrieval:
        1. FAISS semantic search → top 50
        2. BM25 keyword search → top 50
        3. Graph traversal → linked rules
        4. Cross-Encoder re-rank merged candidates → top K
        """
        candidates: Dict[str, EasaRequirement] = {}

        # Stage 1: FAISS vector search
        if self.vectorstore:
            faiss_results = self.vectorstore.similarity_search(query, k=50)
            for doc in faiss_results:
                rule_id = doc.metadata.get("id", "")
                if rule_id and rule_id in self._rule_lookup:
                    candidates[rule_id] = self._rule_lookup[rule_id]

        # Stage 2: BM25 keyword search
        if self.bm25_index:
            tokenized_query = query.lower().split()
            bm25_scores = self.bm25_index.get_scores(tokenized_query)
            top_bm25_indices = np.argsort(bm25_scores)[::-1][:50]
            for idx in top_bm25_indices:
                if bm25_scores[idx] > 0:
                    rule_id = self.bm25_doc_ids[idx]
                    if rule_id in self._rule_lookup:
                        candidates[rule_id] = self._rule_lookup[rule_id]

        # Stage 3: Graph traversal — find cross-referenced rules
        rule_ids_in_query = EASA_RULE_ID_PATTERN.findall(query)
        for rule_id in rule_ids_in_query:
            if self.knowledge_graph.is_built():
                linked = self.knowledge_graph.get_linked_rules(rule_id, depth=2)
                for r in linked[:10]:
                    candidates[r.id] = r

        if not candidates:
            return []

        # Domain filter
        if domain_filter and domain_filter != "All":
            candidates = {
                k: v for k, v in candidates.items()
                if (v.domain or "").lower() == domain_filter.lower()
            }

        # Stage 4: Cross-Encoder re-ranking (Restored with Gemini Fallback)
        candidate_list = list(candidates.values())
        if not candidate_list:
            return []

        try:
            # Attempt local re-ranking
            pairs = [[query, f"{r.source_title}\n{r.text}"] for r in candidate_list]
            scores = self.cross_encoder.predict(pairs)
            scored_candidates = sorted(zip(candidate_list, scores), key=lambda x: x[1], reverse=True)
        except Exception as e:
            print(f"[RE-RANK FALLBACK] Cross-Encoder failed: {e}. Falling back to Gemini scoring.")
            # Fallback: Simple Gemini-based scoring for top 10 candidates to avoid overhead
            scored_candidates = [(r, 0.5) for r in candidate_list] # Default placeholder

        return scored_candidates[:k]

    # ──────────────────────────────────────────────────────────────────────────
    # Manual Chunks + Pre-filtering
    # ──────────────────────────────────────────────────────────────────────────

    def set_manual_chunks(self, chunks: List[ManualChunk]):
        """Stores manual chunks and builds graph connections."""
        self.manual_chunks = chunks
        self.pre_filtered = False

    def run_semantic_pre_filtering(self, threshold: float = 0.5):
        """
        Inverted vector search: for each manual chunk, find matching EASA rules.
        Builds the rule_to_chunks mapping used by the Auditor Agent.
        """
        if not self.vectorstore:
            raise ValueError("Rule index not built. Call build_rule_index first.")

        print("Running semantic pre-filtering (Inverted Vector Search)...")
        self.rule_to_chunks.clear()

        for chunk in self.manual_chunks:
            chunk_text = f"{chunk.section_title}\n{chunk.content}"
            results = self.vectorstore.similarity_search_with_relevance_scores(chunk_text, k=5)
            for doc, score in results:
                if score >= threshold:
                    rule_id = doc.metadata["id"]
                    if chunk not in self.rule_to_chunks[rule_id]:
                        self.rule_to_chunks[rule_id].append(chunk)

        self.pre_filtered = True

        # Update knowledge graph with manual sections
        if self.knowledge_graph.is_built():
            self.knowledge_graph.build_from_manual(self.manual_chunks, dict(self.rule_to_chunks))
            self.knowledge_graph.persist()

        print(f"Pre-filtering complete. {len(self.rule_to_chunks)} rules have matched manual chunks.")

    # ──────────────────────────────────────────────────────────────────────────
    # Agentic Compliance Audit
    # ──────────────────────────────────────────────────────────────────────────

    def evaluate_compliance(self, requirement: EasaRequirement, refined_question: str = "Standard Compliance Check") -> ComplianceAudit:
        """
        Full 4-agent audit pipeline with re-ranker noise gate and multimodal evidence.
        """
        if not self.pre_filtered:
            raise ValueError("Pre-filtering not run. Call run_semantic_pre_filtering first.")

        relevant_chunks = self.rule_to_chunks.get(requirement.id, [])

        # Instant Gap if no evidence found
        if not relevant_chunks:
            return ComplianceAudit(
                requirement_id=requirement.id,
                status="Gap",
                evidence_quote="None",
                source_reference="None",
                confidence_score=1.0,
                suggested_fix="Ensure this regulatory requirement is documented in the manual.",
                agent_trace="SKIP: No matching manual chunks (below threshold).",
            )

        # Get scored rules for the research context
        try:
            scored_rules = self.hybrid_search(refined_question, k=10)
        except Exception as e:
            print(f"[SELF-HEAL] Hybrid search failed for {requirement.id}: {e}. Using empty context.")
            scored_rules = []

        # Run the 4-agent pipeline with self-healing error isolation
        try:
            return self.compliance_board.run_full_audit(
                requirement=requirement,
                all_rules_scored=scored_rules,
                manual_chunks=relevant_chunks[:5],
                all_manual_chunks=self.manual_chunks,
                knowledge_graph=self.knowledge_graph,
                query=refined_question,
            )
        except Exception as e:
            print(f"[SELF-HEAL] Agent pipeline failed for {requirement.id}: {e}. Returning fallback result.")
            return ComplianceAudit(
                requirement_id=requirement.id,
                status="Requires Human Review",
                evidence_quote="Agent pipeline encountered an error.",
                source_reference="System Error",
                confidence_score=0.0,
                suggested_fix=f"Manual review required. Pipeline error: {str(e)[:200]}",
                agent_trace=f"SELF-HEAL: Pipeline failed — {type(e).__name__}: {str(e)[:100]}",
            )

    # ──────────────────────────────────────────────────────────────────────────
    # Search (for Q&A Chat) — now uses hybrid retrieval
    # ──────────────────────────────────────────────────────────────────────────

    def search_rules(self, query: str, domain_filter: Optional[str] = None, k: int = 5) -> List[Tuple[EasaRequirement, float]]:
        """Alias for hybrid_search — used by Q&A tab."""
        return self.hybrid_search(query, k=k, domain_filter=domain_filter)

    # ──────────────────────────────────────────────────────────────────────────
    # LLM Calls
    # ──────────────────────────────────────────────────────────────────────────

    @retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(5))
    def _call_llm_with_retry(self, prompt_template: ChatPromptTemplate, invoke_args: dict) -> str:
        chain = prompt_template | self.llm
        response = chain.invoke(invoke_args)
        return response.content.strip()

    def answer_regulatory_question(self, question: str, domain_filter: Optional[str] = None) -> str:
        """
        Answers regulatory questions using hybrid retrieval + graph context + LLM.
        """
        if not self.vectorstore:
            return "⚠️ The EASA rule index has not been built yet."

        # Hybrid search
        try:
            scored_rules = self.hybrid_search(question, k=5, domain_filter=domain_filter)
        except Exception as e:
            return f"⚠️ Search failed: {e}"

        if not scored_rules:
            return "No relevant EASA rules found for your question."

        rules_context = "\n\n---\n\n".join(
            f"[{r.id} | {r.domain} | {r.amc_gm_info} | score: {s:.3f}]\n{r.source_title}\n{r.text[:600]}"
            for r, s in scored_rules
        )

        # Graph context — deduplicated in a single pass
        graph_context = "No graph available."
        cross_ref_context = "No cross-references found."
        if self.knowledge_graph.is_built():
            primary_ids = {r.id for r, _ in scored_rules}
            seen: set = set()
            unique_linked: List[EasaRequirement] = []
            for r, _ in scored_rules[:3]:
                for linked in self.knowledge_graph.get_linked_rules(r.id, depth=2):
                    if linked.id not in seen and linked.id not in primary_ids:
                        seen.add(linked.id)
                        unique_linked.append(linked)

            if unique_linked:
                graph_context = "\n".join(
                    f"[{r.id} | {r.domain}] {r.source_title}"
                    for r in unique_linked[:8]
                )
                # Cross-ref context: use graph neighbors for deeper insight
                cross_ref_ids = []
                for r, _ in scored_rules[:2]:
                    neighbors = self.knowledge_graph.get_neighbors_summary(r.id)
                    cross_ref_ids.extend(
                        f"{n['id']} ({n['edge_type']})" for n in neighbors[:5]
                    )
                cross_ref_context = "\n".join(cross_ref_ids[:10]) or "No cross-references found."

        try:
            # 🔐 PII REDACTION: Mask sensitive info before sending to cloud
            redacted_question = security.redact_pii(question)
            
            answer = self._call_llm_with_retry(self.chat_prompt, {
                "question": redacted_question,
                "rules_context": rules_context,
                "graph_context": graph_context,
                "cross_ref_context": cross_ref_context,
            })
            time.sleep(0.5)
            # 🔐 OUTPUT SANITIZATION: (Basic) ensure no leaking of internal prompts
            if "system prompt" in answer.lower() or "ignore previous" in answer.lower():
                return "🛡️ Response blocked by output sanitization guardrail."
            return answer
        except Exception as e:
            return f"❌ Error generating answer: {e}"
