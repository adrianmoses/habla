// `defineConfig` comes from vitest/config (not vite) so the `test` block below
// typechecks. Tests cover pure logic only — no jsdom, no component rendering —
// so the default node environment is right (spec #020, Open Question 4).
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
  server: {
    host: 'localhost',
    port: 5173,
    strictPort: true,
    proxy: {
      '/ws/session': {
        target: 'ws://localhost:8000',
        ws: true,
        changeOrigin: true,
      },
      '/health': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
});
