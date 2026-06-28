FROM node:20-alpine

WORKDIR /app

RUN apk add --no-cache curl

# Cache de deps: copia solo los manifests primero.
COPY package.json ./
RUN npm install

# El resto del código se monta por volumen en docker-compose (dev).
# Si se quisiera build estático, descomentar:
# COPY . .
# RUN npm run build

EXPOSE 5173

ENV VITE_API_TARGET=http://api:8000

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
