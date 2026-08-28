import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    port: 5173,
    open: true,
    proxy: {
      '/auth': 'http://localhost:8080',
      '/me': 'http://localhost:8080',
      '/matters': 'http://localhost:8080',
      '/documents': 'http://localhost:8080',
      '/conversations': 'http://localhost:8080',
      '/firms': 'http://localhost:8080',
      '/health': 'http://localhost:8080',
      '/api/doc-search': 'http://localhost:8080',
    },
  },
});
