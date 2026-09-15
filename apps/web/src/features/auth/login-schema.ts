// apps/web/src/features/auth/login-schema.ts

import { z } from 'zod';

import type { LoginInput } from '../../shared/auth/auth-contract';

export const loginSchema = z.object({
  email: z
    .string()
    .trim()
    .toLowerCase()
    .min(3, 'Enter your email address.')
    .max(320, 'The email address is too long.')
    .refine((value) => {
      const parts = value.split('@');
      const local = parts[0];
      const domain = parts[1];

      return (
        parts.length === 2 &&
        local !== undefined &&
        local.length > 0 &&
        domain !== undefined &&
        domain.includes('.')
      );
    }, 'Enter a valid email address.'),

  password: z
    .string()
    .min(1, 'Enter your password.')
    .refine(
      (value) => new TextEncoder().encode(value).length <= 1_024,
      'The password exceeds the supported length.',
    ),
}) satisfies z.ZodType<LoginInput>;
