import { useCallback, useEffect, useState } from "react";
import { ApiError, ERP_BASE, apiFetch } from "./client";

/** Loads a GET endpoint (ERP by default, or `BRAIN_BASE`). `reload()` fetches again and keeps the
 * old data on screen meanwhile. A null path loads nothing. */
export function useApiData<T>(path: string | null, base: string = ERP_BASE) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    if (path === null) return;
    let cancelled = false;
    apiFetch<T>(path, {}, base)
      .then((result) => {
        if (cancelled) return;
        setData(result);
        setError(null);
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        setError(caught instanceof ApiError ? caught.detail : "Could not reach the server");
      });
    return () => {
      cancelled = true;
    };
  }, [path, base, version]);

  const reload = useCallback(() => setVersion((v) => v + 1), []);
  return { data, error, reload, loading: data === null && error === null };
}

/** The message to show for a failed action. */
export function messageOf(caught: unknown): string {
  return caught instanceof ApiError ? caught.detail : "Could not reach the server";
}
