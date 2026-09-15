// apps/web/src/shared/api/retry-after.ts

const SECONDS_PATTERN = /^\d+$/u;

const HTTP_DATE_PATTERN =
  /^(Mon|Tue|Wed|Thu|Fri|Sat|Sun), \d{2} (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{4} \d{2}:\d{2}:\d{2} GMT$/u;

/**
 * Returns the requested delay in milliseconds.
 *
 * null means absent, invalid, or not safely representable.
 * A parsed delay does not authorize an automatic retry.
 * Long delays are never shortened.
 */
export function parseRetryAfter(value: string | null, nowMs: number = Date.now()): number | null {
  if (value === null) {
    return null;
  }

  const normalized = value.trim();

  if (SECONDS_PATTERN.test(normalized)) {
    const milliseconds = Number(normalized) * 1_000;

    return Number.isSafeInteger(milliseconds) ? milliseconds : null;
  }

  if (!HTTP_DATE_PATTERN.test(normalized) || !Number.isSafeInteger(nowMs)) {
    return null;
  }

  const timestamp = Date.parse(normalized);

  // Reject invalid calendar dates and inconsistent weekday names.
  if (!Number.isFinite(timestamp) || new Date(timestamp).toUTCString() !== normalized) {
    return null;
  }

  const delay = Math.max(0, timestamp - nowMs);

  return Number.isSafeInteger(delay) ? delay : null;
}
