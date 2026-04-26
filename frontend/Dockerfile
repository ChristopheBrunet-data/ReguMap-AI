# AeroMind Compliance - Frontend Dockerfile (Vanilla JS)
# Strictly decoupled, zero build overhead.
FROM nginx:alpine

# 1. Clean default Nginx files
RUN rm -rf /usr/share/nginx/html/*

# 2. Copy static assets
COPY index.html /usr/share/nginx/html/
COPY api.js /usr/share/nginx/html/

# 3. Copy hardened Nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
