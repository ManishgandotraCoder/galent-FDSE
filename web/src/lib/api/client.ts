import { logger } from "@/lib/logger";

/** Call the Python API through the Next.js proxy. Paths start with `/api`. */
export async function readApi<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/backend-api${path}`, {
    cache: "no-store",
    ...init,
    headers: init?.body instanceof FormData ? init.headers : { Accept: "application/json", ...init?.headers },
  });
  const data = (await response.json().catch(() => ({}))) as T & { error?: string };
  if (!response.ok) {
    logger.warn("api request failed", { path, status: response.status });
    throw new Error(data.error || `Request failed (${response.status})`);
  }
  return data;
}
