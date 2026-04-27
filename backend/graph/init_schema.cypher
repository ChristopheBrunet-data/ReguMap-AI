// ──────────────────────────────────────────────────────────────────────────────
// ReguMap-AI — Neo4j Schema (DO-326A Deterministic Foundations)
// Labels: :RegulatoryNode, :ManualSection, :Agency
// ──────────────────────────────────────────────────────────────────────────────

// 1. Uniqueness Constraints (Truth anchors)
CREATE CONSTRAINT unique_regnode_id IF NOT EXISTS
  FOR (n:RegulatoryNode) REQUIRE n.node_id IS UNIQUE;

CREATE CONSTRAINT unique_manual_section_id IF NOT EXISTS
  FOR (m:ManualSection) REQUIRE m.section_id IS UNIQUE;

CREATE CONSTRAINT unique_agency_name IF NOT EXISTS
  FOR (a:Agency) REQUIRE a.name IS UNIQUE;

// 2. Cryptographic integrity constraint
CREATE CONSTRAINT unique_regnode_hash IF NOT EXISTS
  FOR (n:RegulatoryNode) REQUIRE n.content_hash IS UNIQUE;

// 3. Performance indexes
CREATE INDEX idx_regnode_type IF NOT EXISTS
  FOR (n:RegulatoryNode) ON (n.node_type);

CREATE INDEX idx_regnode_domain IF NOT EXISTS
  FOR (n:RegulatoryNode) ON (n.domain);

CREATE INDEX idx_regnode_status IF NOT EXISTS
  FOR (n:RegulatoryNode) ON (n.status);

CREATE INDEX idx_regnode_version IF NOT EXISTS
  FOR (n:RegulatoryNode) ON (n.version);

CREATE INDEX idx_manual_page IF NOT EXISTS
  FOR (m:ManualSection) ON (m.page_number);
