// apps/web/src/features/auth/register-schema.ts
import { z } from 'zod';

import type { RegisterInput } from '../../shared/auth/auth-contract';

const DISPLAY_NAME_MAX_LENGTH = 255;
const EMAIL_MAX_LENGTH = 320;
const PASSWORD_MAX_BYTES = 1024;

function utf8Length(value: string): number {
  return new TextEncoder().encode(value).length;
}

const passwordSchema = z
  .string()
  .min(1, 'Create a password.')
  .refine((value) => utf8Length(value) <= PASSWORD_MAX_BYTES, {
    message: `Password must be ${PASSWORD_MAX_BYTES} UTF-8 bytes or fewer.`,
  });

const passwordConfirmationSchema = z
  .string()
  .min(1, 'Confirm your password.')
  .refine((value) => utf8Length(value) <= PASSWORD_MAX_BYTES, {
    message: `Password confirmation must be ${PASSWORD_MAX_BYTES} UTF-8 bytes or fewer.`,
  });

export const registerFormSchema = z
  .object({
    display_name: z
      .string()
      .trim()
      .max(
        DISPLAY_NAME_MAX_LENGTH,
        `Display name must be ${DISPLAY_NAME_MAX_LENGTH} characters or fewer.`,
      ),

    email: z
      .string()
      .trim()
      .toLowerCase()
      .min(1, 'Enter your email address.')
      .min(3, 'Enter a valid email address.')
      .max(EMAIL_MAX_LENGTH, `Email must be ${EMAIL_MAX_LENGTH} characters or fewer.`)
      .email('Enter a valid email address.'),

    password: passwordSchema,
    confirm_password: passwordConfirmationSchema,
  })
  .superRefine((values, context) => {
    if (values.password !== values.confirm_password) {
      context.addIssue({
        code: 'custom',
        path: ['confirm_password'],
        message: 'The passwords do not match.',
      });
    }
  });

export type RegisterFormValues = z.infer<typeof registerFormSchema>;

export function toRegisterInput(values: RegisterFormValues): RegisterInput {
  const displayName = values.display_name.trim();

  return {
    email: values.email,
    password: values.password,
    ...(displayName.length === 0 ? {} : { display_name: displayName }),
  };
}
