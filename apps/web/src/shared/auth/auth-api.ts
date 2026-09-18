// apps/web/src/shared/auth/auth-api.ts

import type { createTransport } from '../api/transport';
import { decodeAuthentication, decodeAuthUser, decodeLogout } from './auth-contract';
import type { LoginInput, RegisterInput } from './auth-contract';

type Transport = ReturnType<typeof createTransport>;

function requestSignal(signal: AbortSignal | undefined) {
  return signal === undefined ? {} : { signal };
}

export function createAuthApi(request: Transport) {
  return {
    login(input: LoginInput, signal?: AbortSignal) {
      return request({
        path: '/v1/auth/login',
        method: 'POST',
        authentication: 'cookie',
        body: {
          kind: 'json',
          // Explicit projection excludes unexpected runtime properties.
          value: {
            email: input.email,
            password: input.password,
          } satisfies LoginInput,
        },
        decode: decodeAuthentication,
        ...requestSignal(signal),
      });
    },

    register(input: RegisterInput, signal?: AbortSignal) {
      return request({
        path: '/v1/auth/register',
        method: 'POST',
        authentication: 'cookie',
        body: {
          kind: 'json',
          value: {
            email: input.email,
            password: input.password,
            ...(input.display_name === undefined ? {} : { display_name: input.display_name }),
          } satisfies RegisterInput,
        },
        decode: decodeAuthentication,
        ...requestSignal(signal),
      });
    },

    refresh(signal?: AbortSignal) {
      return request({
        path: '/v1/auth/refresh',
        method: 'POST',
        authentication: 'cookie',
        decode: decodeAuthentication,
        ...requestSignal(signal),
      });
    },

    currentUser(signal?: AbortSignal) {
      return request({
        path: '/v1/auth/me',
        method: 'GET',
        authentication: 'bearer',
        decode: decodeAuthUser,
        ...requestSignal(signal),
      });
    },

    logout(signal?: AbortSignal) {
      return request({
        path: '/v1/auth/logout',
        method: 'POST',
        authentication: 'bearer-cookie',
        decode: decodeLogout,
        ...requestSignal(signal),
      });
    },
  };
}
