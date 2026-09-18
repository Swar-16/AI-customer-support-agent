// apps/web/tests/e2e/authentication.spec.ts

import process from 'node:process';
import { expect, test } from '@playwright/test';
import type { Locator } from '@playwright/test';

function credentials() {
  const email = process.env.E2E_ADMIN_EMAIL;
  const password = process.env.E2E_ADMIN_PASSWORD;

  if (!email || !password) {
    throw new Error(
      'Set E2E_ADMIN_EMAIL and E2E_ADMIN_PASSWORD to an existing active admin test account.',
    );
  }

  return { email, password };
}

async function fillPassword(input: Locator, password: string): Promise<void> {
  try {
    await input.fill(password);
  } catch {
    throw new Error('The password field could not be filled.');
  }
}

test('admin login, session restoration, confirmed logout, and reload', async ({ page }) => {
  const account = credentials();

  // A fresh browser context has no application session.
  await page.goto('/knowledge');

  await expect(page).toHaveURL('http://localhost:5173/login');
  await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible();

  const signIn = page.getByRole('button', { name: 'Sign in', exact: true });
  await expect(signIn).toBeEnabled();

  await page.getByLabel('Email address', { exact: true }).fill(account.email);
  await fillPassword(page.getByLabel('Password', { exact: true }), account.password);
  await signIn.click();

  // The permitted return destination is preserved through login.
  await expect(page).toHaveURL('http://localhost:5173/knowledge');
  await expect(page.getByRole('heading', { name: 'Knowledge', level: 1 })).toBeVisible();

  const workspaces = page.getByRole('navigation', { name: 'Workspaces' });
  await expect(workspaces.getByRole('link', { name: 'Operations', exact: true })).toBeVisible();
  await expect(workspaces.getByRole('link', { name: 'Knowledge', exact: true })).toHaveAttribute(
    'aria-current',
    'page',
  );
  await expect(workspaces.getByRole('link', { name: 'Customer Chat', exact: true })).toHaveCount(0);

  // Reload destroys the in-memory access token. Returning to Knowledge
  // therefore exercises the real refresh-cookie restoration path.
  await page.reload();

  await expect(page.getByRole('heading', { name: 'Knowledge', level: 1 })).toBeVisible();

  await page.getByRole('link', { name: 'Sign out', exact: true }).click();
  await expect(page).toHaveURL('http://localhost:5173/logout');

  await page.getByRole('button', { name: 'Confirm sign out', exact: true }).click();

  await expect(
    page.getByRole('heading', { name: 'You are signed out', exact: true }),
  ).toBeVisible();

  // Confirmed sign-out automatically returns to login.
  await expect(page).toHaveURL('http://localhost:5173/login', {
    timeout: 5000,
  });

  // A fresh page load must not restore the signed-out session.
  await page.reload();

  await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeEnabled();

  // Verify protected-route behavior after another full navigation.
  await page.goto('/knowledge');

  await expect(page).toHaveURL('http://localhost:5173/login');
  await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Workspaces' })).toHaveCount(0);
});
