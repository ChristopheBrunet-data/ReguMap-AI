const express = require('express');
const { createProxyMiddleware, fixRequestBody } = require('http-proxy-middleware');
const jwt = require('jsonwebtoken');
const { promptInjectionWAF } = require('./waf');

const app = express();
const PORT = 3000;
const BACKEND_URL = process.env.BACKEND_URL || 'http://python-backend:8000';

app.use(express.json({ limit: '10mb' }));
app.use(express.urlencoded({ limit: '10mb', extended: true }));

console.log('--- ReguMap-AI Gateway ---');
console.log(`Target Backend: ${BACKEND_URL}`);

// 1. Logging Middleware
app.use((req, res, next) => {
  console.log(`[GATEWAY] ${req.method} ${req.url} -> Processing...`);
  next();
});

// 2. Cognitive WAF (Prompt Injection Defense)
app.use(promptInjectionWAF);

// 3. JWT Verification Middleware (RBAC proxy bridge)
const JWT_SECRET = process.env.JWT_SECRET;
if (!JWT_SECRET) {
  console.error('[CRITICAL] JWT_SECRET is not set. Gateway shutting down.');
  process.exit(1);
}

app.use((req, res, next) => {
  const publicRoutes = ['/api/v1/auth/login', '/health'];
  if (publicRoutes.includes(req.path)) {
    return next();
  }

  const authHeader = req.headers['authorization'];
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    console.log('[GATEWAY] JWT Missing or Malformed - Blocking request.');
    return res.status(401).json({ error: 'Unauthorized: Missing valid Bearer token' });
  }

  const token = authHeader.split(' ')[1];
  try {
    const decoded = jwt.verify(token, JWT_SECRET);
    req.user = decoded; // Store decoded token data for future use
    console.log(`[GATEWAY] JWT Verified for user: ${decoded.sub || 'unknown'}`);
    next();
  } catch (err) {
    console.log(`[GATEWAY] JWT Verification Failed: ${err.message}`);
    return res.status(401).json({ error: 'Unauthorized: Invalid token' });
  }
});

// Proxy all requests to the Python Backend
const proxyOptions = {
  target: BACKEND_URL,
  changeOrigin: true,
  onProxyReq: fixRequestBody, // RESTREAM the body after express.json()
  proxyTimeout: 900000, // 15 minutes (900,000 ms)
  timeout: 900000,
  pathRewrite: {
    '^/': '/', // keep paths as is
  },
};

app.use('/', createProxyMiddleware(proxyOptions));

app.listen(PORT, '0.0.0.0', () => {
  console.log(`Gateway listening on port ${PORT}`);
  console.log(`External Access: http://localhost:${PORT}`);
});
