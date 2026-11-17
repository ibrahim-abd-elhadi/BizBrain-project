import { useCallback, useEffect, useState } from "react";
import { ApiError, apiFetch } from "./client";

/** Loads a GET endpoint. `reload()` fetches again and keeps the old data on screen meanwhile. */
export function useApiData<T>(path: string) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let cancelled = false;
    apiFetch<T>(path)
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
  }, [path, version]);

  const reload = useCallback(() => setVersion((v) => v + 1), []);
  return { data, error, reload, loading: data === null && error === null };
}

/** The message to show for a failed action. */
export function messageOf(caught: unknown): string {
  return caught instanceof ApiError ? caught.detail : "Could not reach the server";
}
