import process from 'node:process';
import { expect, test } from '@playwright/test';
import type { Locator, Page } from '@playwright/test';

const conversationUrl = /\/chat\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function credentials() {
  const email = process.env.E2E_CUSTOMER_EMAIL;
  const password = process.env.E2E_CUSTOMER_PASSWORD;

  if (!email || !password) {
    throw new Error(
      'Set E2E_CUSTOMER_EMAIL and E2E_CUSTOMER_PASSWORD to an active customer test account.',
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

async function signIn(page: Page) {
  const account = credentials();

  await page.goto('/chat');

  await expect(page).toHaveURL('http://localhost:5173/login');

  const submit = page.getByRole('button', {
    name: 'Sign in',
    exact: true,
  });

  await expect(submit).toBeEnabled();

  await page.getByLabel('Email address', { exact: true }).fill(account.email);

  await fillPassword(page.getByLabel('Password', { exact: true }), account.password);

  await submit.click();

  await expect(page).toHaveURL('http://localhost:5173/chat');
  await expect(
    page.getByRole('heading', {
      name: 'Customer Chat',
      level: 1,
    }),
  ).toBeVisible();
}

async function createConversation(page: Page): Promise<string> {
  await page.getByRole('button', { name: 'New conversation', exact: true }).click();

  await expect(page).toHaveURL(conversationUrl);
  await expect(page.getByText('No messages yet.', { exact: true })).toBeVisible();

  await expect(page.getByRole('textbox', { name: 'Your message', exact: true })).toBeEnabled();

  return new URL(page.url()).pathname;
}

async function signOut(page: Page) {
  await page.getByRole('link', { name: 'Sign out', exact: true }).click();

  await page
    .getByRole('button', {
      name: 'Confirm sign out',
      exact: true,
    })
    .click();

  await expect(
    page.getByRole('heading', {
      name: 'You are signed out',
      exact: true,
    }),
  ).toBeVisible();
}

test('customer creates, reopens, and restores a conversation', async ({ page }) => {
  await signIn(page);
  const path = await createConversation(page);

  // Identify this conversation by its confirmed URL, not its
  // non-unique "Untitled conversation" label.
  await page.goto('/chat');

  const conversationLink = page
    .getByRole('navigation', { name: 'Conversations', exact: true })
    .locator(`a[href="${path}"]`);

  await expect(conversationLink).toBeVisible();
  await conversationLink.click();

  await expect(page).toHaveURL(`http://localhost:5173${path}`);
  await expect(page.getByText('No messages yet.', { exact: true })).toBeVisible();

  // Exercises cookie-based session restoration and persisted reads.
  await page.reload();

  await expect(page).toHaveURL(`http://localhost:5173${path}`);
  await expect(page.getByText('No messages yet.', { exact: true })).toBeVisible();

  await expect(page.getByRole('button', { name: 'Send message', exact: true })).toBeEnabled();

  await signOut(page);

  await page.goto(path);
  await expect(page).toHaveURL('http://localhost:5173/login');
});

test('live AI saves a customer message and assistant response', async ({ page }) => {
  test.skip(
    process.env.E2E_LIVE_AI !== '1',
    'Requires live providers and published knowledge relevant to the test question.',
  );

  test.setTimeout(90_000);

  await signIn(page);
  const path = await createConversation(page);

  // Synthetic test content only. Adjust this question to match
  // a stable policy in your published development knowledge.
  const question = 'What is your return policy?';

  const composer = page.getByRole('textbox', {
    name: 'Your message',
    exact: true,
  });

  await composer.fill(question);

  await page.getByRole('button', { name: 'Send message', exact: true }).click();

  const customerMessage = page.getByRole('article', {
    name: 'Message from You',
    exact: true,
  });

  const assistantMessage = page.getByRole('article', {
    name: 'Message from Assistant',
    exact: true,
  });

  // A failure, escalation, or no-response workflow does not satisfy
  // this particular grounded-answer test.
  await expect(assistantMessage).toHaveCount(1, { timeout: 45_000 });
  await expect(customerMessage).toHaveCount(1);

  await expect(customerMessage.locator('.chat-history__content')).toHaveText(question);

  // Check non-empty content without putting provider-generated text
  // into an assertion's expected value.
  await expect
    .poll(async () =>
      assistantMessage
        .locator('.chat-history__content')
        .evaluate((element) => Boolean(element.textContent?.trim())),
    )
    .toBe(true);

  await expect(composer).toHaveValue('');

  await page.reload();

  await expect(page).toHaveURL(`http://localhost:5173${path}`);
  await expect(customerMessage).toHaveCount(1);
  await expect(assistantMessage).toHaveCount(1);

  await expect(customerMessage.locator('.chat-history__content')).toHaveText(question);

  await expect
    .poll(async () =>
      assistantMessage
        .locator('.chat-history__content')
        .evaluate((element) => Boolean(element.textContent?.trim())),
    )
    .toBe(true);

  await signOut(page);
});
