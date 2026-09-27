import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

export default defineConfig(({ mode }) => {
  // loadEnv with an empty prefix so VITE_PROXY_TARGET is readable here.
  const env = loadEnv(mode, process.cwd(), '')
  // :8000 is the loadtest stub (scripts/loadtest_server.py) — NEVER the default.
  // The real FastAPI backend runs on :8001.
  const target = env.VITE_PROXY_TARGET || 'http://127.0.0.1:8001'

  return {
    plugins: [react()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, 'src'),
      },
    },
    server: {
      port: 5173,
      // Proxy the API and the WebSocket to the backend during development, so
      // the app can use same-origin relative URLs and no backend host is
      // hardcoded in application code.
      proxy: {
        '/api': { target, changeOrigin: true },
        '/ws': { target, ws: true, changeOrigin: true },
        '/health': { target, changeOrigin: true },
        '/metrics': { target, changeOrigin: true },
      },
    },
  }
})
