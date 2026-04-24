import hashlib

def generate_node_hash(node_id: str, content: str) -> str:
    """
    Generates a deterministic SHA-256 hash for a regulatory node.
    Combining node_id and content ensures that any change in text 
    or classification results in a new hash.
    """
    # Normalize input: strip whitespace to avoid hash divergence due to formatting
    payload = f"{node_id.strip()}|{content.strip()}"
    
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()

if __name__ == "__main__":
    # Quick sanity check
    h1 = generate_node_hash("RULE-01", "This is a test content.")
    h2 = generate_node_hash("RULE-01", "This is a test content.")
    h3 = generate_node_hash("RULE-01", "This is a test content!")
    
    assert h1 == h2
    assert h1 != h3
    print(f"Hash 1: {h1}")
    print(f"Hash 3: {h3}")
    print("Hasher sanity check passed.")
