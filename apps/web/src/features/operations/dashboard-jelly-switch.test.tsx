// apps/web/src/features/operations/dashboard-jelly-switch.test.tsx
import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { DashboardJellySwitch } from './dashboard-jelly-switch';

const periodOptions = [
  {
    value: '24h',
    label: '24 hours',
  },
  {
    value: '7d',
    label: '7 days',
  },
  {
    value: '30d',
    label: '30 days',
  },
] as const;

type Period = (typeof periodOptions)[number]['value'];

function PeriodHarness({ initialValue = '24h' }: { readonly initialValue?: Period }) {
  const [value, setValue] = useState<Period>(initialValue);

  return (
    <>
      <DashboardJellySwitch
        label="Reporting period"
        value={value}
        options={periodOptions}
        tone="accent"
        onChange={setValue}
      />

      <output aria-label="Selected period">{value}</output>
    </>
  );
}

describe('DashboardJellySwitch', () => {
  it('exposes the selected option through aria-pressed', () => {
    render(<PeriodHarness />);

    expect(
      screen.getByRole('group', {
        name: 'Reporting period',
      }),
    ).toBeInTheDocument();

    expect(
      screen.getByRole('button', {
        name: '24 hours',
      }),
    ).toHaveAttribute('aria-pressed', 'true');

    expect(
      screen.getByRole('button', {
        name: '7 days',
      }),
    ).toHaveAttribute('aria-pressed', 'false');

    expect(
      screen.getByRole('button', {
        name: '30 days',
      }),
    ).toHaveAttribute('aria-pressed', 'false');
  });

  it('changes the selected value when another option is clicked', () => {
    render(<PeriodHarness />);

    fireEvent.click(
      screen.getByRole('button', {
        name: '7 days',
      }),
    );

    expect(screen.getByLabelText('Selected period')).toHaveTextContent('7d');

    expect(
      screen.getByRole('button', {
        name: '7 days',
      }),
    ).toHaveAttribute('aria-pressed', 'true');
  });

  it('applies forward movement when moving to a later option', () => {
    const { container } = render(<PeriodHarness />);

    fireEvent.click(
      screen.getByRole('button', {
        name: '30 days',
      }),
    );

    const indicator = container.querySelector('.dashboard-jelly-switch__indicator');

    expect(indicator).toHaveClass('is-moving');
    expect(indicator).toHaveClass('is-forward');
    expect(indicator).not.toHaveClass('is-backward');
  });

  it('applies backward movement when moving to an earlier option', () => {
    const { container } = render(<PeriodHarness initialValue="30d" />);

    fireEvent.click(
      screen.getByRole('button', {
        name: '7 days',
      }),
    );

    const indicator = container.querySelector('.dashboard-jelly-switch__indicator');

    expect(indicator).toHaveClass('is-moving');
    expect(indicator).toHaveClass('is-backward');
  });

  it('does not call onChange when the selected option is clicked', () => {
    const onChange = vi.fn();

    render(
      <DashboardJellySwitch
        label="Reporting period"
        value="24h"
        options={periodOptions}
        onChange={onChange}
      />,
    );

    fireEvent.click(
      screen.getByRole('button', {
        name: '24 hours',
      }),
    );

    expect(onChange).not.toHaveBeenCalled();
  });

  it('does not allow a disabled option to be selected', () => {
    const onChange = vi.fn();

    render(
      <DashboardJellySwitch
        label="Reporting period"
        value="24h"
        options={[
          periodOptions[0],
          {
            ...periodOptions[1],
            disabled: true,
          },
          periodOptions[2],
        ]}
        onChange={onChange}
      />,
    );

    const disabledOption = screen.getByRole('button', {
      name: '7 days',
    });

    expect(disabledOption).toBeDisabled();

    fireEvent.click(disabledOption);

    expect(onChange).not.toHaveBeenCalled();
  });

  it('disables every option when the complete control is disabled', () => {
    render(
      <DashboardJellySwitch
        label="Reporting period"
        value="24h"
        options={periodOptions}
        disabled
        onChange={vi.fn()}
      />,
    );

    for (const button of screen.getAllByRole('button')) {
      expect(button).toBeDisabled();
    }
  });

  it('applies the requested visual tone', () => {
    const { container } = render(
      <DashboardJellySwitch
        label="Reporting period"
        value="24h"
        options={periodOptions}
        tone="accent"
        onChange={vi.fn()}
      />,
    );

    expect(container.querySelector('.dashboard-jelly-switch')).toHaveClass(
      'dashboard-jelly-switch--accent',
    );
  });

  it('uses the light tone by default', () => {
    const { container } = render(
      <DashboardJellySwitch
        label="Reporting period"
        value="24h"
        options={periodOptions}
        onChange={vi.fn()}
      />,
    );

    expect(container.querySelector('.dashboard-jelly-switch')).toHaveClass(
      'dashboard-jelly-switch--light',
    );
  });
});
