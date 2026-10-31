FROM node:25-alpine as builder

WORKDIR /app

COPY package.json package-lock.json* yarn.lock* ./
# No consistent lockfile (yarn.lock is out of sync with package.json), so npm re-resolves on every build.
# npm 10.8.2 (node:20) crashes in its peer-dependency resolver on the current registry state
# ("Cannot read properties of null (reading 'edgesOut')"); skip peer resolution, as the CI job does.
RUN npm install --legacy-peer-deps

COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27-alpine

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

USER nginx
EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
