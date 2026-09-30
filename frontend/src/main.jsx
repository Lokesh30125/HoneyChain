import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import App from '@/App';
import '@/index.css';

/**
 * Application entry point.
 *
 * `StrictMode` is enabled deliberately: it surfaces unsafe patterns (missing
 * effect cleanups, unstable dependencies) during development.
 */
const container = document.getElementById('root');

if (!container) {
  throw new Error('Root container #root was not found in index.html');
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
