import os
import re
import json
import logging
import datetime
import jwt
from cryptography.fernet import Fernet
from typing import Optional, List, Dict
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Public API — only these are exported by `from .vault import *`
__all__ = [
    "encrypt_data",
    "decrypt_data",
    "secure_save_json",
    "secure_load_json",
    "redact_pii",
    "sanitize_input",
    "SecurityException",
    "log_audit_event",
    "generate_session_token",
    "verify_session_token",
    "check_permission",
    "ROLES",
]

# ──────────────────────────────────────────────────────────────────────────────
# 1. SECRET MANAGEMENT
# ──────────────────────────────────────────────────────────────────────────────

# Lazy init: only load .env when secrets are first accessed,
# not at module import time (prevents side-effects during testing)
_secrets_initialized = False
CIPHER = None
JWT_SECRET = None

def _init_secrets():
    """Initialize encryption and JWT secrets on first use."""
    global _secrets_initialized, CIPHER, JWT_SECRET
    if _secrets_initialized:
        return
    _secrets_initialized = True

    load_dotenv()
    encryption_key = os.getenv("APP_ENCRYPTION_KEY")
    if not encryption_key:
        encryption_key = Fernet.generate_key().decode()
        logger.warning(
            "APP_ENCRYPTION_KEY not found in environment. Using an ephemeral key for this session. "
            "Any data encrypted in this session will be UNRECOVERABLE after restart. "
            "Set APP_ENCRYPTION_KEY in your .env file for persistent encryption."
        )
    CIPHER = Fernet(encryption_key.encode())
    JWT_SECRET = os.getenv("JWT_SECRET")



# ──────────────────────────────────────────────────────────────────────────────
# 2. DATA PROTECTION (AES-256)
# ──────────────────────────────────────────────────────────────────────────────

def encrypt_data(data: bytes) -> bytes:
    """Encrypts raw bytes using AES-256."""
    _init_secrets()
    return CIPHER.encrypt(data)

def decrypt_data(token: bytes) -> bytes:
    """Decrypts AES-256 encrypted bytes."""
    _init_secrets()
    return CIPHER.decrypt(token)

def secure_save_json(filepath: str, data: dict):
    """Encrypts and saves JSON data to disk."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    json_str = json.dumps(data, ensure_ascii=False).encode('utf-8')
    encrypted_data = encrypt_data(json_str)
    with open(filepath, "wb") as f:
        f.write(encrypted_data)

def secure_load_json(filepath: str) -> Optional[dict]:
    """Loads and decrypts JSON data from disk."""
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, "rb") as f:
            encrypted_data = f.read()
        decrypted_data = decrypt_data(encrypted_data)
        return json.loads(decrypted_data.decode('utf-8'))
    except Exception as e:
        logging.error(f"Failed to decrypt/load secure JSON {filepath}: {e}")
        return None

# ──────────────────────────────────────────────────────────────────────────────
# 3. PII REDACTION
# ──────────────────────────────────────────────────────────────────────────────

PII_PATTERNS = {
    "EMAIL": re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'),
    "PHONE": re.compile(r'\b\d{3}[-.\s]??\d{3}[-.\s]??\d{4}\b|\b\+\d{1,3}[-.\s]??\d{2,3}[-.\s]??\d{3,4}[-.\s]??\d{3,4}\b'),
    "NAME_STRICT": re.compile(r'\b(?:Mr\.|Ms\.|Mrs\.|Dr\.)\s+[A-Z][a-z]+\s+[A-Z][a-z]+\b'),
}

def redact_pii(text: str) -> str:
    """Detects and masks PII before sending to Cloud LLM."""
    redacted = text
    for label, pattern in PII_PATTERNS.items():
        redacted = pattern.sub(f"[REDACTED_{label}]", redacted)
    return redacted

# ──────────────────────────────────────────────────────────────────────────────
# 4. LLM GUARDRAILS (Prompt Injection Protection)
# ──────────────────────────────────────────────────────────────────────────────

INJECTION_KEYWORDS = [
    "ignore previous instructions",
    "system prompt",
    "forget everything",
    "you are now an evil",
    "as an ai language model",
    "override",
    "jailbreak"
]

def sanitize_input(user_input: str) -> str:
    """Checks for prompt injection patterns and sanitizes input."""
    lowered = user_input.lower()
    for kw in INJECTION_KEYWORDS:
        if kw in lowered:
            logger.warning(f"PROMPT INJECTION DETECTED: {user_input}")
            raise SecurityException(f"Potential malicious instruction detected: '{kw}'")
    
    # Path traversal / absolute path check
    if ".." in user_input:
        logger.warning(f"PATH TRAVERSAL BLOCKED: {user_input}")
        raise SecurityException("Path traversal patterns are not allowed in queries.")
    if user_input.startswith("/") or (len(user_input) >= 2 and user_input[1] == ":"):
        logger.warning(f"ABSOLUTE PATH BLOCKED: {user_input}")
        raise SecurityException("Absolute file paths are not allowed in queries.")
        
    return user_input

class SecurityException(Exception):
    pass

# ──────────────────────────────────────────────────────────────────────────────
# 5. AUDIT & OBSERVABILITY (Forensic Logging)
# ──────────────────────────────────────────────────────────────────────────────

LOG_DIR = "data/logs"
os.makedirs(LOG_DIR, exist_ok=True)
AUDIT_LOG = os.path.join(LOG_DIR, "audit.log")

def log_audit_event(user_id: str, action: str, data_accessed: str = "N/A", ip_address: str = "127.0.0.1"):
    """Creates a forensic audit entry."""
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    entry = {
        "timestamp": timestamp,
        "user_id": user_id,
        "action": action,
        "data_accessed": data_accessed,
        "ip_address": ip_address
    }
    # Log to internal logger
    logging.info(f"AUDIT | {user_id} | {action} | {data_accessed}")
    
    # Persist to encrypted log file
    all_logs = secure_load_json(AUDIT_LOG + ".enc") or []
    all_logs.append(entry)
    secure_save_json(AUDIT_LOG + ".enc", all_logs)

# ──────────────────────────────────────────────────────────────────────────────
# 6. IAM (JWT & RBAC)
# ──────────────────────────────────────────────────────────────────────────────

ROLES = {
    "ADMIN": ["system", "write", "read"],
    "SAFETY_MANAGER": ["write", "read"],
    "AUDITOR": ["read"]
}

def generate_session_token(user_id: str, role: str) -> str:
    """Generates a short-lived JWT session token."""
    _init_secrets()
    if not JWT_SECRET:
        raise SecurityException("JWT_SECRET environment variable is not set.")
    
    payload = {
        "user_id": user_id,
        "role": role,
        "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=2)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def verify_session_token(token: str) -> Optional[dict]:
    """Verifies a JWT session token."""
    _init_secrets()
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None

def check_permission(role: str, required_permission: str) -> bool:
    """Verifies if a role has a specific permission."""
    return required_permission in ROLES.get(role, [])
