# Frontend Next.js - Dockerfile multi-stage
# Supporta sia sviluppo che produzione tramite TARGETPLATFORM e variabili d'ambiente

# Stage base: installa dipendenze
FROM node:22-alpine AS base
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# Stage dependencies: solo per development
FROM base AS dependencies
COPY . .

# Stage builder: per production build
FROM base AS builder
ENV NODE_ENV=production
COPY . .
RUN npm run build

# Stage production: immagine finale minimale per production
FROM node:22-alpine AS production
WORKDIR /app
COPY --from=builder /app/package.json /app/package-lock.json ./
RUN npm ci --only=production
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0

EXPOSE 3000
CMD ["node", "server.js"]

# Stage development: default se non specificato
FROM dependencies AS development
ENV NODE_ENV=development \
    PORT=3000 \
    HOSTNAME=0.0.0.0

EXPOSE 3000
CMD ["npm", "run", "dev"]
