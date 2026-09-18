import { describe, expect, it } from 'vitest';

import { PublicConfigurationError, readPublicConfig } from './public-config';

describe('public API configuration', () => {
  it('defaults to the page origin', () => {
    expect(readPublicConfig(undefined, 'https://support.example.com')).toEqual({
      apiOrigin: 'https://support.example.com',
    });
  });

  it('accepts an empty value for same-origin deployment', () => {
    expect(readPublicConfig('', 'https://support.example.com')).toEqual({
      apiOrigin: 'https://support.example.com',
    });
  });

  it('supports local frontend and API ports on the same hostname', () => {
    expect(readPublicConfig('http://localhost:8000', 'http://localhost:5173')).toEqual({
      apiOrigin: 'http://localhost:8000',
    });
  });

  it('normalizes an HTTPS origin', () => {
    expect(readPublicConfig('https://API.example.com:443/', 'https://support.example.com')).toEqual(
      {
        apiOrigin: 'https://api.example.com',
      },
    );
  });

  it.each([
    '/v1',
    '//api.example.com',
    'https://api.example.com/v1',
    'https://user:secret@api.example.com',
    'https://api.example.com?token=secret',
    'https://api.example.com#fragment',
    ' https://api.example.com',
    'https://api.example.com\\path',
    'ftp://api.example.com',
    'http://api.example.com',
    123,
    null,
  ])('rejects invalid configuration without echoing it', (value) => {
    expect(() => readPublicConfig(value, 'https://support.example.com')).toThrow(
      PublicConfigurationError,
    );

    expect(() => readPublicConfig(value, 'https://support.example.com')).toThrow(
      'The application API configuration is invalid.',
    );
  });

  it('rejects mixed localhost and IP-address configuration', () => {
    expect(() => readPublicConfig('http://127.0.0.1:8000', 'http://localhost:5173')).toThrow(
      PublicConfigurationError,
    );
  });

  it('rejects an HTTP API from an HTTPS page', () => {
    expect(() => readPublicConfig('http://localhost:8000', 'https://localhost:5173')).toThrow(
      PublicConfigurationError,
    );
  });

  it('returns immutable configuration', () => {
    expect(Object.isFrozen(readPublicConfig('', 'https://support.example.com'))).toBe(true);
  });
});
