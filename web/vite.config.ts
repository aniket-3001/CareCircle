import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// In development the API runs on :8000 (python -m graphmem.api); in production FastAPI serves the built files itself.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { '/v1': 'http://127.0.0.1:8000', '/demo': 'http://127.0.0.1:8000', '/healthz': 'http://127.0.0.1:8000' } },
  build: { outDir: 'dist', sourcemap: false },
  test: { environment: 'jsdom', globals: true },
});
