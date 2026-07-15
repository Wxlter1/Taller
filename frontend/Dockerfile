FROM node:20-alpine

WORKDIR /app

# Vacío por defecto: el frontend deduce la URL del backend desde el host de la
# página en tiempo de ejecución. Solo definir para apuntar a otro backend.
ARG VITE_API_URL=
ENV VITE_API_URL=${VITE_API_URL}

COPY package.json package-lock.json* ./
RUN npm install

COPY . ./
RUN npm run build

EXPOSE 5173
CMD ["npm", "run", "preview", "--", "--host", "0.0.0.0", "--port", "5173"]
