// AI-customer-support-agent\apps\web\src\shared\config\public-config.ts
export interface PublicConfig {
  readonly apiOrigin: string;
}

export class PublicConfigurationError extends Error {
  constructor() {
    super('The application API configuration is invalid.');
    this.name = 'PublicConfigurationError';
  }
}

function parseOrigin(value: string): URL {
  if (value !== value.trim() || /[\s\\?#]/u.test(value) || !/^https?:\/\//u.test(value)) {
    throw new PublicConfigurationError();
  }

  let url: URL;

  try {
    url = new URL(value);
  } catch {
    throw new PublicConfigurationError();
  }

  if (
    !url.hostname ||
    url.username !== '' ||
    url.password !== '' ||
    url.pathname !== '/' ||
    url.search !== '' ||
    url.hash !== ''
  ) {
    throw new PublicConfigurationError();
  }

  return url;
}

export function readPublicConfig(rawApiBaseUrl: unknown, pageOrigin: string): PublicConfig {
  if (rawApiBaseUrl !== undefined && typeof rawApiBaseUrl !== 'string') {
    throw new PublicConfigurationError();
  }

  const page = parseOrigin(pageOrigin);
  const api = parseOrigin(
    rawApiBaseUrl === undefined || rawApiBaseUrl === '' ? page.origin : rawApiBaseUrl,
  );

  if (api.protocol === 'http:') {
    const loopbackHosts = new Set(['localhost', '127.0.0.1', '[::1]']);

    // HTTP is limited to a consistent local-development hostname.
    // HTTPS pages must never send authentication to an HTTP API.
    if (
      page.protocol !== 'http:' ||
      !loopbackHosts.has(api.hostname) ||
      api.hostname !== page.hostname
    ) {
      throw new PublicConfigurationError();
    }
  }

  return Object.freeze({ apiOrigin: api.origin });
}
