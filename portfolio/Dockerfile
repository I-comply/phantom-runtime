# Not built or run in the authoring environment (no Docker daemon). Build context: portfolio/
# Build the site first on a trusted machine:  PWX_SITE_URL=https://your-domain npm run build
FROM node:22-slim
WORKDIR /app
COPY package.json ./
COPY src ./src
COPY dist ./dist
ENV NODE_ENV=production PORT=8080 HOST=0.0.0.0 PWX_INQUIRY_FILE=/data/inquiries.jsonl PWX_METRICS_FILE=/data/metrics.json
RUN mkdir /data && chown node:node /data
USER node
VOLUME ["/data"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD node -e "fetch('http://127.0.0.1:8080/healthz').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "src/server.mjs"]
