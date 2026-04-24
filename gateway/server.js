const express = require('express');
const { createProxyMiddleware, fixRequestBody } = require('http-proxy-middleware');
const { promptInjectionWAF } = require('./waf');

const app = express();
const PORT = 3000;
const BACKEND_URL = process.env.BACKEND_URL || 'http://python-backend:8000';

app.use(express.json()); // Required to read body for WAF

console.log('--- ReguMap-AI Gateway ---');
console.log(`Target Backend: ${BACKEND_URL}`);

// 1. Logging Middleware
app.use((req, res, next) => {
  console.log(`[GATEWAY] ${req.method} ${req.url} -> Processing...`);
  next();
});

// 2. Cognitive WAF (Prompt Injection Defense)
app.use(promptInjectionWAF);

// Proxy all requests to the Python Backend
app.use('/', createProxyMiddleware({
  target: BACKEND_URL,
  changeOrigin: true,
  onProxyReq: fixRequestBody, // RESTREAM the body after express.json()
  pathRewrite: {
    '^/': '/', // keep paths as is
  },
}));

app.listen(PORT, '0.0.0.0', () => {
  console.log(`Gateway listening on port ${PORT}`);
  console.log(`External Access: http://localhost:${PORT}`);
});
