FROM node:20-alpine as builder

WORKDIR /app

COPY package.json package-lock.json* yarn.lock* ./
RUN npm install

COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27-alpine

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

USER nginx
EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
