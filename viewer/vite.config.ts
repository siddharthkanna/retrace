import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Requests to /api are passed on to the investigator service, so the page and
// the API share one address in the browser.
const investigator = process.env.INVESTIGATOR_URL ?? 'http://localhost:8002'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    proxy: {
      '/api': {
        target: investigator,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
