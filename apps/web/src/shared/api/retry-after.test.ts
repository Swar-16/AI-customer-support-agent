// apps/web/src/shared/api/retry-after.test.ts

import { describe, expect, it } from 'vitest';

import { parseRetryAfter } from './retry-after';

describe('parseRetryAfter', () => {
  it('parses the confirmed analytics delay', () => {
    expect(parseRetryAfter('5')).toBe(5_000);
  });

  it.each([
    ['0', 0],
    ['1', 1_000],
    [' 5 ', 5_000],
    ['005', 5_000],
    ['86400', 86_400_000],
  ])('parses seconds %j as %i milliseconds', (value, expected) => {
    expect(parseRetryAfter(value)).toBe(expected);
  });

  it('preserves a long delay without imposing a shorter retry interval', () => {
    expect(parseRetryAfter('604800')).toBe(604_800_000);
  });

  it('calculates the remaining delay for an HTTP date', () => {
    const now = Date.UTC(2026, 8, 15, 12, 0, 0);

    expect(parseRetryAfter('Tue, 15 Sep 2026 12:00:05 GMT', now)).toBe(5_000);
  });

  it('preserves millisecond precision in the current time', () => {
    const now = Date.UTC(2026, 8, 15, 12, 0, 0, 250);

    expect(parseRetryAfter('Tue, 15 Sep 2026 12:00:05 GMT', now)).toBe(4_750);
  });

  it('returns zero for a date that has already passed', () => {
    const now = Date.UTC(2026, 8, 15, 12, 0, 10);

    expect(parseRetryAfter('Tue, 15 Sep 2026 12:00:05 GMT', now)).toBe(0);
  });

  it.each([
    null,
    '',
    ' ',
    '-5',
    '+5',
    '1.5',
    '1e3',
    'Infinity',
    'NaN',
    '5 seconds',
    '5, 10',
    '9007199254740991',
    '2026-09-15T12:00:05Z',
    'Mon, 15 Sep 2026 12:00:05 GMT',
    'Tue, 31 Feb 2026 12:00:05 GMT',
    'Tue, 15 Sep 2026 25:00:05 GMT',
    '<script>alert(1)</script>',
  ])('rejects absent or invalid values: %j', (value) => {
    expect(parseRetryAfter(value)).toBeNull();
  });

  it.each([Number.NaN, Number.POSITIVE_INFINITY, 1.5])(
    'rejects an invalid clock value for date-based delays: %s',
    (now) => {
      expect(parseRetryAfter('Tue, 15 Sep 2026 12:00:05 GMT', now)).toBeNull();
    },
  );

  it('does not require a clock for a seconds-based delay', () => {
    expect(parseRetryAfter('5', Number.NaN)).toBe(5_000);
  });
});
