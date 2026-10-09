import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In development the API runs on :8000; the proxy keeps the browser on a single origin.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://localhost:8000' } },
})
