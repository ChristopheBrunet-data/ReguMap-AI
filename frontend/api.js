/**
 * AeroMind Compliance - Lightweight API Handler
 * Strictly decoupled, zero business logic.
 */

const GATEWAY_URL = 'http://localhost:3000';

async function secureFetch(endpoint, options = {}) {
    const token = sessionStorage.getItem('jwt_token');

    const headers = {
        'Content-Type': 'application/json',
        ...(token && { 'Authorization': `Bearer ${token}` }),
        ...options.headers
    };

    try {
        const response = await fetch(`${GATEWAY_URL}${endpoint}`, {
            ...options,
            headers
        });

        if (response.status === 401) {
            console.error("[SECURITY] Unauthorized: Token expired or invalid.");
            sessionStorage.removeItem('jwt_token');
            window.location.reload(); // Force re-auth
            return null;
        }

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.message || `HTTP Error ${response.status}`);
        }

        return await response.json();
    } catch (err) {
        console.error(`[API ERROR] ${err.message}`);
        throw err;
    }
}

/**
 * Perform a compliance audit query.
 */
async function queryCompliance(question) {
    return secureFetch('/api/v1/audit/ask', {
        method: 'POST',
        body: JSON.stringify({ question })
    });
}
