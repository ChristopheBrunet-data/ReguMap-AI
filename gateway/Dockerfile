# ReguMap-AI — Node.js Gateway Dockerfile
# Role: External Boundary (DO-326A)

FROM node:20-slim

WORKDIR /app

COPY package*.json ./
RUN npm install --production

# Inclusion of all local modules including waf.js
COPY . .

# Expose port 3000 to the host
EXPOSE 3000

CMD ["node", "server.js"]
