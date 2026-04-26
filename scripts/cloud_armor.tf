# AeroMind Compliance - Cloud Armor & Load Balancing (T8.4)
# Sprint 8: Edge Defense Layer (DO-326A Compliance)

# 1. Politique de Sécurité Cloud Armor (WAF L7)
resource "google_compute_security_policy" "aeromind_security_policy" {
  name        = "aeromind-security-policy"
  description = "Protection L7 contre OWASP Top 10 et DDoS pour AeroMind Compliance"

  # Règle 1: Rate Limiting (Contre le Brute Force et Denial of Wallet)
  rule {
    action   = "throttle"
    priority = "100"
    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }
    rate_limit_options {
      conform_action = "allow"
      exceed_action  = "deny(429)"
      enforce_on_key = "IP"
      rate_limit_threshold {
        count        = 100
        interval_sec = 60
      }
    }
    description = "Limitation à 100 requêtes par minute par IP"
  }

  # Règle 2: Protection contre les injections SQL (Preconfigured WAF)
  rule {
    action   = "deny(403)"
    priority = "1000"
    match {
      expr {
        expression = "evaluatePreconfiguredExpr('sqli-v33-stable')"
      }
    }
    description = "Blocage des injections SQL"
  }

  # Règle 3: Protection contre les attaques XSS
  rule {
    action   = "deny(403)"
    priority = "1010"
    match {
      expr {
        expression = "evaluatePreconfiguredExpr('xss-v33-stable')"
      }
    }
    description = "Blocage des attaques XSS"
  }

  # Règle 4: Protection contre l'exécution de code à distance (RCE)
  rule {
    action   = "deny(403)"
    priority = "1020"
    match {
      expr {
        expression = "evaluatePreconfiguredExpr('rce-v33-stable')"
      }
    }
    description = "Blocage des tentatives RCE (Remote Code Execution)"
  }

  # Règle par défaut (Autoriser le reste)
  rule {
    action   = "allow"
    priority = "2147483647"
    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }
    description = "Autorisation par défaut du trafic légitime"
  }
}

# 2. Adresse IP Publique Statique
resource "google_compute_global_address" "aeromind_lb_ip" {
  name = "aeromind-lb-ip"
}

# 3. Serverless Network Endpoint Group (NEG) pour Cloud Run
resource "google_compute_region_network_endpoint_group" "frontend_neg" {
  name                  = "aeromind-frontend-neg"
  network_endpoint_type = "SERVERLESS"
  region                = "europe-west1"
  cloud_run {
    service = "aeromind-frontend"
  }
}

# 4. Backend Service (Connexion du NEG et du Cloud Armor)
resource "google_compute_backend_service" "aeromind_backend_service" {
  name            = "aeromind-backend-service"
  protocol        = "HTTP"
  port_name       = "http"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  security_policy = google_compute_security_policy.aeromind_security_policy.name

  backend {
    group = google_compute_region_network_endpoint_group.frontend_neg.id
  }
}

# 5. URL Map (Routage du trafic)
resource "google_compute_url_map" "aeromind_url_map" {
  name            = "aeromind-url-map"
  default_service = google_compute_backend_service.aeromind_backend_service.id
}

# 6. Target HTTP Proxy & Forwarding Rule (Exposition finale)
resource "google_compute_target_http_proxy" "aeromind_http_proxy" {
  name    = "aeromind-http-proxy"
  url_map = google_compute_url_map.aeromind_url_map.id
}

resource "google_compute_global_forwarding_rule" "aeromind_forwarding_rule" {
  name                  = "aeromind-forwarding-rule"
  ip_protocol           = "TCP"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  port_range            = "80"
  target                = google_compute_target_http_proxy.aeromind_http_proxy.id
  ip_address            = google_compute_global_address.aeromind_lb_ip.id
}
