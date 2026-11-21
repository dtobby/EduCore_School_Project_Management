import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      // All /api/* requests are forwarded to the Django backend.
      // This avoids CORS in development — browser sees one origin (localhost:5173).
      '/api': {
        target: 'http://backend:8000',
        changeOrigin: true,
      },
    },
  },
})
