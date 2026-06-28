import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

// En Docker el hostname del backend es "api" (servicio de docker-compose).
// En desarrollo fuera de Docker, el proxy cae a localhost:8000.
const API_TARGET = process.env.VITE_API_TARGET ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: API_TARGET,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
        // El dev server de Vite, por defecto, puede bufferizar respuestas
        // ``text/event-stream`` (SSE) hasta que el backend cierra el
        // stream. Eso hace que los tokens del LLM lleguen todos juntos al
        // final en lugar de ir apareciendo progresivamente. Forzamos
        // ``X-Accel-Buffering: no`` y ``Cache-Control: no-transform`` en
        // la respuesta para desactivar el buffering en cualquier proxy
        // intermedio (nginx, Vite mismo, etc.).
        configure(proxy) {
          proxy.on('proxyRes', (proxyRes) => {
            proxyRes.headers['x-accel-buffering'] = 'no'
            proxyRes.headers['cache-control'] = 'no-cache, no-transform'
          })
        },
      },
    },
  },
})
