import { expect, it } from 'vitest';

import config from '../../vite.config.js';

it('proxies both API and media to the backend', async () => {
  // Found by driving the real app: only /api was proxied, so every uploaded
  // photo 404'd in development while working in production, where a single
  // origin serves both. That divergence is the one thing the proxy exists to
  // prevent, so both paths are pinned here.
  const resolved = typeof config === 'function' ? await config({ mode: 'development' }) : config;

  expect(Object.keys(resolved.server.proxy).sort()).toEqual(['/api', '/media']);
  for (const rule of Object.values(resolved.server.proxy)) {
    expect(rule.target).toBe('http://localhost:8000');
  }
});

it('serves from /admin/, so built asset URLs resolve behind the path', () => {
  expect(config.base).toBe('/admin/');
});
