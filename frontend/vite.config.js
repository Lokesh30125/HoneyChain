import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

/**
 * Vite configuration.
 *
 * The dev server proxies `/api` to the FastAPI backend so the browser only ever
 * talks to one origin. That keeps cookies (the HttpOnly refresh token) first
 * party and avoids CORS during development; the backend's CORS allow-list is
 * still configured for deployments where the API lives on its own host.
 */
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const backendUrl = env.VITE_PROXY_TARGET || 'https://honeychain-lgj8.onrender.com';

  return {
    plugins: [react()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    server: {
      host: true, // listen on 0.0.0.0 so the dev server is reachable from a VM/container
      port: 5173,
      strictPort: true,
      // Vite rejects requests whose Host header it does not recognise. Set
      // VITE_ALLOWED_HOSTS (comma separated) to pin this down in a shared or
      // hosted environment; the default accepts any host for local/dev-in-VM
      // use, where the development server is reachable through a proxy domain.
      allowedHosts: env.VITE_ALLOWED_HOSTS
        ? env.VITE_ALLOWED_HOSTS.split(',').map((host) => host.trim()).filter(Boolean)
        : true,
      proxy: {
        '/api': {
          target: backendUrl,
          changeOrigin: true,
          secure: false,
        },
      },
    },
    preview: {
      host: true,
      port: 4173,
      allowedHosts: true,
      proxy: {
        '/api': {
          target: backendUrl,
          changeOrigin: true,
          secure: false,
        },
      },
    },
    build: {
      outDir: 'dist',
      sourcemap: mode !== 'production',
      chunkSizeWarningLimit: 900,
      rollupOptions: {
        output: {
          manualChunks: {
            vendor: ['react', 'react-dom', 'react-router-dom'],
            charts: ['recharts'],
            motion: ['framer-motion'],
          },
        },
      },
    },
  };
});
