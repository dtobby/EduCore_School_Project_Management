FROM node:20-alpine

WORKDIR /app

# Install dependencies first (cached layer — only re-runs if package.json changes)
COPY package*.json ./
RUN npm install

# Copy source (overwritten by the volume mount in development)
COPY . .

CMD ["npm", "run", "dev"]
