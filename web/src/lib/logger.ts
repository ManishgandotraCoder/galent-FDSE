/**
 * Small logger for the Next.js server and the browser.
 *
 * Server routes read LOG_LEVEL. The browser reads NEXT_PUBLIC_LOG_LEVEL.
 * Levels: debug, info, warn, error. Production defaults to info.
 */

type Level = "debug" | "info" | "warn" | "error";

const RANK: Record<Level, number> = {
  debug: 10,
  info: 20,
  warn: 30,
  error: 40,
};

function currentLevel(): Level {
  const raw = (process.env.NEXT_PUBLIC_LOG_LEVEL || process.env.LOG_LEVEL || "").toLowerCase();
  if (raw === "debug" || raw === "info" || raw === "warn" || raw === "error") return raw;
  return process.env.NODE_ENV === "production" ? "info" : "debug";
}

function write(level: Level, message: string, details?: Record<string, unknown>) {
  if (RANK[level] < RANK[currentLevel()]) return;
  const suffix = details ? ` ${JSON.stringify(details)}` : "";
  const line = `[ap] ${message}${suffix}`;
  if (level === "error") console.error(line);
  else if (level === "warn") console.warn(line);
  else console.info(line);
}

export const logger = {
  debug(message: string, details?: Record<string, unknown>) {
    write("debug", message, details);
  },
  info(message: string, details?: Record<string, unknown>) {
    write("info", message, details);
  },
  warn(message: string, details?: Record<string, unknown>) {
    write("warn", message, details);
  },
  error(message: string, details?: Record<string, unknown>) {
    write("error", message, details);
  },
};
