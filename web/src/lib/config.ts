/**
 * Server configuration from the environment.
 *
 * Do not import this from a React component. The browser talks to
 * `/backend-api`, and the proxy in `app/backend-api` reads `backendUrl`.
 * Copy `web/.env.example` to `web/.env.local` to override the defaults.
 */

function trimSlash(url: string): string {
  return url.replace(/\/$/, "");
}

export const config = {
  backendUrl: trimSlash(process.env.BACKEND_URL || "http://127.0.0.1:8000"),
};
