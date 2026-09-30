/**
 * Periodically probes `GET /api/v1/health` so the UI can show whether the
 * backend is reachable. Used by the public footer and the dev banner — it is
 * the frontend half of the "verify frontend ↔ backend connectivity" check.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { getHealth } from '@/services/systemService';
import { normaliseError } from '@/utils/errors';

const DEFAULT_INTERVAL = Number(import.meta.env.VITE_HEALTH_POLL_INTERVAL || 60000);

export function useApiHealth({ intervalMs = DEFAULT_INTERVAL, enabled = true } = {}) {
  const [state, setState] = useState({
    status: 'checking', // checking | online | offline
    service: null,
    checkedAt: null,
    error: null,
  });
  const mounted = useRef(true);

  const check = useCallback(async () => {
    try {
      const data = await getHealth();
      if (!mounted.current) return;
      setState({
        status: 'online',
        service: data?.service || 'HoneyChain API',
        checkedAt: new Date(),
        error: null,
      });
    } catch (caught) {
      if (!mounted.current) return;
      setState({
        status: 'offline',
        service: null,
        checkedAt: new Date(),
        error: normaliseError(caught),
      });
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    if (!enabled) return undefined;

    check();
    if (!intervalMs) return () => { mounted.current = false; };

    const timer = setInterval(check, intervalMs);
    return () => {
      mounted.current = false;
      clearInterval(timer);
    };
  }, [check, intervalMs, enabled]);

  return { ...state, refresh: check };
}

export default useApiHealth;
