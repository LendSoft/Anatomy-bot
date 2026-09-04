# syntax=docker/dockerfile:1.7

# ------------------------------------------------------------------ deps
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
# npm ci нужен package-lock.json; при первой сборке его может не быть
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

# ------------------------------------------------------------------- dev
FROM node:22-alpine AS dev
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

# ----------------------------------------------------------------- build
FROM node:22-alpine AS build
WORKDIR /app
ARG VITE_API_BASE_URL=/api/v1
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

# ------------------------------------------------------------------ prod
FROM nginx:1.27-alpine AS prod
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
