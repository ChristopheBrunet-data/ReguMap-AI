import os
import json
import shutil
import logging
import argparse
import hashlib
from datetime import datetime
from typing import List, Dict, Any, Optional

from dotenv import load_dotenv
from neo4j import GraphDatabase
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings

# Internal imports
import security

# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────

load_dotenv()

BLACKLISTED_REFS = ["CM-AS-001"] # skip-compliance-check
BACKUP_DIR = "data/backups"
LOG_DIR = "data/logs"
FAISS_INDEX_PATH = "data/vector_db/faiss_index"

# Ensure directories exist
os.makedirs(BACKUP_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "purge_audit.log")),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("purge_utility")

# ──────────────────────────────────────────────────────────────────────────────
# Audit Logger
# ──────────────────────────────────────────────────────────────────────────────

class AuditTrail:
    def __init__(self):
        self.entries = []

    def add_entry(self, component: str, ref_id: str, content: str, reason: str):
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        entry = {
            "timestamp": datetime.now().isoformat(),
            "component": component,
            "ref_id": ref_id,
            "content_hash": content_hash,
            "reason": reason
        }
        self.entries.append(entry)
        logger.info(f"PURGE [{component}]: {ref_id} (Hash: {content_hash[:10]}...)")

    def save(self):
        log_path = os.path.join(LOG_DIR, f"purge_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        with open(log_path, "w") as f:
            json.dump(self.entries, f, indent=4)
        logger.info(f"Audit report saved to {log_path}")

# ──────────────────────────────────────────────────────────────────────────────
# Neo4j Purger
# ──────────────────────────────────────────────────────────────────────────────

class Neo4jPurger:
    def __init__(self, uri: str, user: str, password: str):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.audit = AuditTrail()

    def close(self):
        self.driver.close()

    def backup(self):
        """Perform a JSON backup of nodes containing the blacklisted references."""
        logger.info("Backing up Neo4j nodes...")
        with self.driver.session() as session:
            for ref in BLACKLISTED_REFS:
                result = session.run(
                    "MATCH (n) WHERE any(prop in keys(n) WHERE n[prop] CONTAINS $ref) RETURN n",
                    ref=ref
                )
                nodes = [dict(record["n"]) for record in result]
                if nodes:
                    backup_path = os.path.join(BACKUP_DIR, f"neo4j_backup_{ref}_{datetime.now().strftime('%Y%m%d')}.json")
                    with open(backup_path, "w") as f:
                        json.dump(nodes, f, indent=4)
                    logger.info(f"Backup for {ref} saved: {len(nodes)} nodes.")

    def purge(self, dry_run: bool = True):
        logger.info(f"Starting Neo4j purge (Dry-run: {dry_run})")
        with self.driver.session() as session:
            for ref in BLACKLISTED_REFS:
                # Find nodes for audit logging
                result = session.run(
                    "MATCH (n) WHERE any(prop in keys(n) WHERE n[prop] CONTAINS $ref) RETURN id(n) as id, n",
                    ref=ref
                )
                for record in result:
                    node_id = record["id"]
                    node_data = str(dict(record["n"]))
                    self.audit.add_entry("NEO4J", str(node_id), node_data, f"Contains {ref}")

                if not dry_run:
                    # Perform actual deletion
                    delete_result = session.run(
                        "MATCH (n) WHERE any(prop in keys(n) WHERE n[prop] CONTAINS $ref) DETACH DELETE n",
                        ref=ref
                    )
                    counters = delete_result.consume().counters
                    logger.info(f"Deleted {counters.nodes_deleted} nodes and {counters.relationships_deleted} relationships for {ref}.")
                else:
                    logger.info(f"DRY RUN: Would delete nodes matching {ref}")

# ──────────────────────────────────────────────────────────────────────────────
# Vector Purger (FAISS)
# ──────────────────────────────────────────────────────────────────────────────

class VectorPurger:
    def __init__(self, index_path: str):
        self.index_path = index_path
        self.embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
        self.audit = AuditTrail()
        self.vectorstore = None

    def _decrypt_load(self) -> str:
        temp_path = "data/temp_purge_faiss"
        os.makedirs(temp_path, exist_ok=True)
        for f_name in ["index.faiss", "index.pkl"]:
            enc_path = os.path.join(self.index_path, f_name + ".enc")
            if os.path.exists(enc_path):
                with open(enc_path, "rb") as f:
                    data = security.decrypt_data(f.read())
                with open(os.path.join(temp_path, f_name), "wb") as f:
                    f.write(data)
        return temp_path

    def _encrypt_save(self, temp_path: str):
        self.vectorstore.save_local(temp_path)
        for f_name in ["index.faiss", "index.pkl"]:
            with open(os.path.join(temp_path, f_name), "rb") as f:
                data = security.encrypt_data(f.read())
            with open(os.path.join(self.index_path, f_name + ".enc"), "wb") as f:
                f.write(data)
        # Cleanup temp
        shutil.rmtree(temp_path)

    def backup(self):
        logger.info("Backing up FAISS index...")
        backup_path = os.path.join(BACKUP_DIR, f"faiss_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        shutil.copytree(self.index_path, backup_path)
        logger.info(f"FAISS backup saved to {backup_path}")

    def purge(self, dry_run: bool = True):
        logger.info(f"Starting FAISS purge (Dry-run: {dry_run})")
        if not os.path.exists(self.index_path):
            logger.warning("FAISS index not found. Skipping.")
            return

        temp_path = self._decrypt_load()
        self.vectorstore = FAISS.load_local(temp_path, self.embeddings, allow_dangerous_deserialization=True)

        ids_to_delete = []
        docstore = self.vectorstore.docstore._dict

        for doc_id, doc in docstore.items():
            content = doc.page_content
            metadata = str(doc.metadata)
            
            should_purge = False
            for ref in BLACKLISTED_REFS:
                if ref in content or ref in metadata:
                    should_purge = True
                    self.audit.add_entry("FAISS", doc_id, content, f"Contains {ref}")
                    break
            
            if should_purge:
                ids_to_delete.append(doc_id)

        if not dry_run:
            if ids_to_delete:
                self.vectorstore.delete(ids_to_delete)
                logger.info(f"Deleted {len(ids_to_delete)} vectors from FAISS.")
                self._encrypt_save(temp_path)
            else:
                logger.info("No blacklisted refs found in FAISS.")
                shutil.rmtree(temp_path)
        else:
            logger.info(f"DRY RUN: Would delete {len(ids_to_delete)} vectors from FAISS.")
            shutil.rmtree(temp_path)

# ──────────────────────────────────────────────────────────────────────────────
# Verification Logic
# ──────────────────────────────────────────────────────────────────────────────

def verify_purge(dry_run: bool):
    if dry_run:
        logger.info("Verification skipped in dry-run mode.")
        return

    logger.info("Verifying purge success (Translation Validation)...")
    
    # 1. Verify Neo4j
    neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_pass = os.getenv("NEO4J_PASSWORD", "password")
    
    try:
        driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_pass))
        with driver.session() as session:
            for ref in BLACKLISTED_REFS:
                result = session.run(
                    "MATCH (n) WHERE any(prop in keys(n) WHERE n[prop] CONTAINS $ref) RETURN count(n) as count",
                    ref=ref
                )
                count = result.single()["count"]
                if count > 0:
                    logger.error(f"VERIFICATION FAILED: {count} nodes still found for {ref} in Neo4j.")
                else:
                    logger.info(f"VERIFICATION SUCCESS: 0 nodes found for {ref} in Neo4j.")
        driver.close()
    except Exception as e:
        logger.warning(f"Neo4j Verification could not be completed: {e}")

    # 2. Verify FAISS
    try:
        v_purger = VectorPurger(FAISS_INDEX_PATH)
        temp_path = v_purger._decrypt_load()
        v_purger.vectorstore = FAISS.load_local(temp_path, v_purger.embeddings, allow_dangerous_deserialization=True)
        
        for ref in BLACKLISTED_REFS:
            results = v_purger.vectorstore.similarity_search(ref, k=1)
            # Check if any result actually contains the ref (similarity search might return something unrelated)
            found = False
            for doc in results:
                if ref in doc.page_content or ref in str(doc.metadata):
                    found = True
                    break
            
            if found:
                logger.error(f"VERIFICATION FAILED: Reference {ref} still discoverable in FAISS.")
            else:
                logger.info(f"VERIFICATION SUCCESS: Reference {ref} is no longer found in FAISS.")
        
        shutil.rmtree(temp_path)
    except Exception as e:
        logger.warning(f"FAISS Verification could not be completed: {e}")

# ──────────────────────────────────────────────────────────────────────────────
# CLI Entry Point
# ──────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Purge obsolete regulatory references from ReguMap-AI data layer.")
    parser.add_argument("--force", action="store_true", help="Execute the purge. Without this flag, it runs in dry-run mode.")
    parser.add_argument("--skip-neo4j", action="store_true", help="Skip Neo4j purge.")
    parser.add_argument("--skip-vector", action="store_true", help="Skip FAISS purge.")
    args = parser.parse_args()

    dry_run = not args.force
    if dry_run:
        logger.info("!!! RUNNING IN DRY-RUN MODE (No changes will be made) !!!")

    audit_trail = AuditTrail()

    # Neo4j Purge
    if not args.skip_neo4j:
        neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        neo4j_pass = os.getenv("NEO4J_PASSWORD", "password")
        
        try:
            purger = Neo4jPurger(neo4j_uri, neo4j_user, neo4j_pass)
            purger.audit = audit_trail
            if not dry_run:
                purger.backup()
            purger.purge(dry_run=dry_run)
            purger.close()
        except Exception as e:
            logger.error(f"Neo4j Purge Failed: {e}")

    # Vector Purge
    if not args.skip_vector:
        try:
            v_purger = VectorPurger(FAISS_INDEX_PATH)
            v_purger.audit = audit_trail
            if not dry_run:
                v_purger.backup()
            v_purger.purge(dry_run=dry_run)
        except Exception as e:
            logger.error(f"Vector Purge Failed: {e}")

    # Finalize Audit
    audit_trail.save()

    # Verification
    verify_purge(dry_run=dry_run)

    logger.info("Maintenance task complete.")

if __name__ == "__main__":
    main()
