import react from '@vitejs/plugin-react';
import vike from 'vike/plugin';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react(), vike()],
  server: {
    port: 3000,
    proxy: {
      // Same-origin in the browser, exactly as in production. The storefront
      // and the API share an origin so that the cart token cookie/header story
      // and the SEO endpoints (/robots.txt, /sitemap.xml) all live at one host.
      '/api': { target: 'http://localhost:8000', changeOrigin: false },
      '/media': { target: 'http://localhost:8000', changeOrigin: false },
      '/robots.txt': { target: 'http://localhost:8000', changeOrigin: false },
      '/sitemap.xml': { target: 'http://localhost:8000', changeOrigin: false },
      '^/sitemap-.*\.xml$': { target: 'http://localhost:8000', changeOrigin: false },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './test/setup.js',
    css: false,
  },
});
