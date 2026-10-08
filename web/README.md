# Workbench

Next.js app for review, evaluation, and the client readout. It proxies API calls to the Python service.

```bash
npm install
npm run dev
```

Open http://localhost:3000. Copy `.env.example` to `.env.local` to point at a different API or change the log level.

```
src/app/            pages and route handlers
src/components/     layout, workbench, eval, intake
src/lib/api/        response types and the fetch client
src/lib/format.ts   text shown on screen
src/lib/config.ts   BACKEND_URL (server only)
src/lib/logger.ts   log lines for the proxy and the browser
```

`BACKEND_URL` is read by the server. The browser calls `/backend-api`, which forwards to that address.
