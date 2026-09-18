// apps/web/src/app/startup-failure.test.tsx

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { StartupFailure } from './startup-failure';

describe('StartupFailure', () => {
  it('provides a named main region and configuration guidance', () => {
    render(<StartupFailure reason="configuration" />);

    expect(screen.getByRole('main', { name: 'Support AI could not start.' })).toBeInTheDocument();

    expect(screen.getByRole('alert')).toHaveTextContent(
      'The application connection settings are invalid.',
    );

    expect(screen.getByText('Sign-in and workspaces are unavailable.')).toBeInTheDocument();
  });

  it('provides safe guidance for other initialization failures', () => {
    render(<StartupFailure reason="startup" />);

    expect(screen.getByRole('alert')).toHaveTextContent(
      'The application could not initialize in this browser.',
    );

    expect(screen.getByRole('alert')).not.toHaveTextContent('connection settings are invalid');
  });
});
