# Etapa 1: compilar la app con Node (esta imagen pesada se descarta)
FROM node:20-alpine AS build

WORKDIR /app

# Vacío por defecto: el frontend deduce la URL del backend desde el host de la
# página en tiempo de ejecución. Solo definir para apuntar a otro backend.
ARG VITE_API_URL=
ENV VITE_API_URL=${VITE_API_URL}

COPY package.json package-lock.json* ./
RUN npm install

COPY . ./
RUN npm run build

# Etapa 2: servir los estáticos con nginx (imagen final ~50 MB)
FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
