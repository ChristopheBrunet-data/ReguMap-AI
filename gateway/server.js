const express = require('express');
const { createProxyMiddleware } = require('http-proxy-middleware');

const app = express();
const PORT = 3000;
const BACKEND_URL = process.env.BACKEND_URL || 'http://python-backend:8000';

console.log('--- ReguMap-AI Gateway ---');
console.log(`Target Backend: ${BACKEND_URL}`);

// DO-326A Border Guard Logic:
// In a production scenario, we would add JWT validation, 
// Rate Limiting, and WAF rules here.
app.use((req, res, next) => {
  console.log(`[GATEWAY] ${req.method} ${req.url} -> Proxying to Backend`);
  next();
});

// Proxy all requests to the Python Backend
app.use('/', createProxyMiddleware({
  target: BACKEND_URL,
  changeOrigin: true,
  pathRewrite: {
    '^/': '/', // keep paths as is
  },
}));

app.listen(PORT, '0.0.0.0', () => {
  console.log(`Gateway listening on port ${PORT}`);
  console.log(`External Access: http://localhost:${PORT}`);
});
