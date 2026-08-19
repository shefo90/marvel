import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  // Served from marvel.com/admin, not from a domain root, so built asset URLs
  // have to carry the path or every chunk 404s in production.
  base: '/admin/',
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // The browser then sees one origin, exactly as it will in production.
      // Without this the API needs CORS middleware it does not have, and
      // development would be testing a topology we never ship.
      '/api': { target: 'http://localhost:8000', changeOrigin: false },
      // Uploaded imagery, served by the API's static mount at MEDIA_URL_PREFIX.
      // Without this every product photo 404s in development while working
      // perfectly in production, where one origin serves both -- the exact
      // divergence the proxy exists to prevent.
      '/media': { target: 'http://localhost:8000', changeOrigin: false },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.js',
    css: false,
  },
});
