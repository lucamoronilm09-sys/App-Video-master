# Frontend Next.js - Dockerfile per sviluppo
FROM node:22-alpine

WORKDIR /app

# Copia i file di package per l'installazione delle dipendenze
COPY package.json package-lock.json ./

# Installa le dipendenze
RUN npm ci

# Copia il resto del codice
COPY . .

# Esponi la porta
EXPOSE 3000

# Variabili d'ambiente
ENV NODE_ENV=development \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# Comando per avviare in modalità sviluppo con hot-reload
CMD ["npm", "run", "dev"]
