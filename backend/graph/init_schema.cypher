// Contraintes d'unicité pour les ID (Vérité mathématique)
CREATE CONSTRAINT unique_regulation_id IF NOT EXISTS FOR (r:Regulation) REQUIRE r.id IS UNIQUE;
CREATE CONSTRAINT unique_requirement_id IF NOT EXISTS FOR (req:Requirement) REQUIRE req.id IS UNIQUE;

// Contraintes d'unicité pour les hash cryptographiques (Traçabilité)
CREATE CONSTRAINT unique_regulation_hash IF NOT EXISTS FOR (r:Regulation) REQUIRE r.sha256_hash IS UNIQUE;
CREATE CONSTRAINT unique_requirement_hash IF NOT EXISTS FOR (req:Requirement) REQUIRE req.sha256_hash IS UNIQUE;

// Index B-Tree pour les propriétés de recherche courantes (Performances déterministes)
CREATE INDEX index_regulation_domain IF NOT EXISTS FOR (r:Regulation) ON (r.domain);
CREATE INDEX index_requirement_domain IF NOT EXISTS FOR (req:Requirement) ON (req.domain);
CREATE INDEX index_requirement_amc_gm IF NOT EXISTS FOR (req:Requirement) ON (req.amc_gm_info);
