/**
 * ReguMap-AI WAF (Web Application Firewall)
 * Heuristic Prompt & Cypher Injection Detection (DO-326A Compliance)
 */

const INJECTION_PATTERNS = [
    // 1. LLM Prompt Injection (Jailbreaks & Leaking)
    /(ignore|disregard)\s+(all\s+)?(previous\s+)?(instructions|directions|prompts)/i,
    /(system\s+prompt|you\s+are\s+now|bypass|jailbreak|override)/i,
    /forget\s+(everything|your\s+instructions)/i,
    /as\s+an\s+ai\s+language\s+model/i,
    
    // 2. Cypher Injection (Graph Integrity Protection)
    /\b(MATCH|DELETE|DROP|MERGE|CREATE|REMOVE|DETACH|LIMIT|SKIP)\b/i,
    /--|UNION|SELECT|INSERT|UPDATE/i // SQL-like patterns that might be tried
];

/**
 * Heuristic scanner for injection signatures.
 * @param {string} text 
 * @returns {boolean}
 */
function detectInjection(text) {
    if (!text || typeof text !== 'string') return false;
    
    for (const pattern of INJECTION_PATTERNS) {
        if (pattern.test(text)) {
            return true;
        }
    }
    return false;
}

/**
 * Express Middleware for ReguMap-AI WAF.
 * This is the first line of defense before authentication.
 */
function promptInjectionWAF(req, res, next) {
    // Scan body, query parameters and path
    const userInput = JSON.stringify(req.body) + JSON.stringify(req.query) + req.url;

    if (detectInjection(userInput)) {
        console.warn(`[SECURITY VIOLATION] Injection Attempt Detected: Source IP ${req.ip}`);
        console.warn(`[AUDIT] Target URL: ${req.url} | Content: ${userInput.substring(0, 100)}...`);
        
        return res.status(403).json({
            error: "Security Violation: Malicious Content Detected",
            code: "SEC-WAF-VPC-403",
            message: "Your request was blocked by the ReguMap-AI Cognitive WAF (DO-326A Compliance)."
        });
    }

    next();
}

module.exports = {
    detectInjection,
    promptInjectionWAF
};
