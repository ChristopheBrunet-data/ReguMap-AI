# AeroMind Compliance - Infrastructure as Code (GCP)
# Sprint 8: Foundation Layer

provider "google" {
  project = "regumap-ai-493622"
  region  = "europe-west1"
}

# 1. Réseau VPC (Isolé)
resource "google_compute_network" "aeromind_vpc" {
  name                    = "aeromind-vpc"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "aeromind_subnet" {
  name          = "aeromind-private-subnet"
  ip_cidr_range = "10.164.0.0/24"
  network       = google_compute_network.aeromind_vpc.id
  region        = "europe-west1"
}

# 2. Connecteur VPC Serverless (Pour Cloud Run)
resource "google_vpc_access_connector" "connector" {
  name          = "aeromind-vpc-connector"
  region        = "europe-west1"
  ip_cidr_range = "10.8.0.0/28"
  network       = google_compute_network.aeromind_vpc.name
}

# 3. Instance Neo4j (Stateful / Private IP Only)
resource "google_compute_instance" "neo4j_db" {
  name         = "aeromind-neo4j"
  machine_type = "e2-standard-2"
  zone         = "europe-west1-b"

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-11"
      size  = 50
    }
  }

  network_interface {
    subnetwork = google_compute_subnetwork.aeromind_subnet.id
    # Pas d'access_config {} => Pas d'IP Publique (Sécurité DO-326A)
  }

  metadata_startup_script = <<-EOT
    #!/bin/bash
    apt-get update
    apt-get install -y docker.io
    docker run -d --name neo4j \
      -p 7474:7474 -p 7687:7687 \
      -e NEO4J_AUTH=neo4j/password \
      -e NEO4J_PLUGINS='["apoc"]' \
      neo4j:5.15
  EOT
}

# 4. Firewall (Autoriser uniquement le trafic interne)
resource "google_compute_firewall" "allow_internal" {
  name    = "aeromind-allow-internal"
  network = google_compute_network.aeromind_vpc.name

  allow {
    protocol = "tcp"
    ports    = ["7474", "7687", "8000"]
  }

  source_ranges = ["10.164.0.0/24", "10.8.0.0/28"]
}
