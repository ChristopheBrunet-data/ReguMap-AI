/**
 * ReguMap-AI WAF (Web Application Firewall)
 * Heuristic Prompt Injection Detection (DO-326A Compliance)
 */

const INJECTION_PATTERNS = [
    /(ignore|disregard)\s+(all\s+)?(previous\s+)?(instructions|directions|prompts)/i,
    /(system\s+prompt|you\s+are\s+now|bypass|jailbreak)/i,
    /forget\s+(everything|your\s+instructions)/i,
    /override\s+safety/i,
    /as\s+an\s+ai\s+language\s+model/i // Often used in jailbreak attempts
];

/**
 * Heuristic scanner for prompt injection signatures.
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
 * Express Middleware for Prompt Injection WAF.
 */
function promptInjectionWAF(req, res, next) {
    // We expect the query in the request body (JSON) or as a query param
    const userInput = req.body?.query || req.query?.query || "";

    if (userInput && detectInjection(userInput)) {
        console.warn(`[SECURITY VIOLATION] Prompt Injection Detected: "${userInput}"`);
        console.warn(`[AUDIT] Source IP: ${req.ip} | Method: ${req.method} | URL: ${req.url}`);
        
        return res.status(403).json({
            error: "Security Violation: Prompt Injection Detected",
            code: "SEC-PROMPT-INJ-001",
            message: "Your request was blocked by the ReguMap-AI Cognitive WAF (DO-326A Compliance)."
        });
    }

    next();
}

module.exports = {
    detectInjection,
    promptInjectionWAF
};
