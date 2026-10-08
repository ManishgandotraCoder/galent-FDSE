import { NextRequest, NextResponse } from "next/server";

import { config } from "@/lib/config";
import { logger } from "@/lib/logger";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 900;

const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailers",
  "transfer-encoding",
  "upgrade",
  "host",
]);

async function forward(request: NextRequest, path: string[]) {
  const started = Date.now();
  const target = new URL(`${config.backendUrl}/${path.join("/")}`);
  target.search = request.nextUrl.search;

  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase())) headers.set(key, value);
  });

  const method = request.method;
  const init: RequestInit & { duplex?: "half" } = {
    method,
    headers,
    cache: "no-store",
    redirect: "manual",
  };
  if (method !== "GET" && method !== "HEAD") {
    init.body = request.body;
    init.duplex = "half";
  }

  try {
    const response = await fetch(target, init);
    const outgoing = new Headers();
    response.headers.forEach((value, key) => {
      if (!HOP_BY_HOP.has(key.toLowerCase())) outgoing.set(key, value);
    });
    logger.info("proxied request", {
      method,
      path: `/${path.join("/")}`,
      status: response.status,
      duration_ms: Date.now() - started,
    });
    return new NextResponse(response.body, { status: response.status, headers: outgoing });
  } catch (error) {
    logger.error("proxy failed", {
      method,
      path: `/${path.join("/")}`,
      duration_ms: Date.now() - started,
      error: error instanceof Error ? error.message : "unknown",
    });
    return NextResponse.json(
      { error: "The accounts payable API is not running." },
      { status: 502 },
    );
  }
}

type RouteContext = { params: Promise<{ path: string[] }> };

async function handle(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  return forward(request, path);
}

export const GET = handle;
export const POST = handle;
export const PUT = handle;
export const PATCH = handle;
export const DELETE = handle;
