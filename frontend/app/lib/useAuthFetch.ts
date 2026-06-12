import { useAuth } from "@clerk/nextjs";
import { useCallback } from "react";

/**
 * Returns a fetch wrapper that automatically attaches the Clerk JWT
 * as an Authorization: Bearer header on every request.
 */
export function useAuthFetch() {
  const { getToken } = useAuth();

  return useCallback(
    async (url: string, options: RequestInit = {}): Promise<Response> => {
      const token = await getToken();
      return fetch(url, {
        ...options,
        headers: {
          ...(options.headers || {}),
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      });
    },
    [getToken]
  );
}
