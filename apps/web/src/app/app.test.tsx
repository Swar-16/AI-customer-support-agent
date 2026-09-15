// AI-customer-support-agent\apps\web\src\app\app.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { App } from './app';

describe('application entry', () => {
  it('provides a named main landmark and explains unavailable integration', () => {
    render(<App />);

    expect(screen.getByRole('main', { name: 'A thoughtful space for support.' })).toBeVisible();

    expect(
      screen.getByText(
        'Setup in progress. Sign-in and workspace connections are not available yet.',
      ),
    ).toBeVisible();
  });
});
