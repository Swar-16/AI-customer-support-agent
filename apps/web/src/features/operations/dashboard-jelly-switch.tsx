// apps/web/src/features/operations/dashboard-jelly-switch.tsx
import { useState, type CSSProperties, type ReactNode } from 'react';

interface JellySwitchOption<Value extends string> {
  readonly value: Value;
  readonly label: ReactNode;
  readonly disabled?: boolean;
}

interface DashboardJellySwitchProps<Value extends string> {
  readonly label: string;
  readonly value: Value;
  readonly options: readonly JellySwitchOption<Value>[];
  readonly disabled?: boolean;
  readonly className?: string;
  readonly tone?: 'light' | 'accent';
  readonly onChange: (value: Value) => void;
}

interface JellySwitchStyle extends CSSProperties {
  '--jelly-count': number;
  '--jelly-from': string;
  '--jelly-middle': string;
  '--jelly-to': string;
}

interface JellyTravel {
  readonly from: number;
  readonly to: number;
  readonly revision: number;
}

export function DashboardJellySwitch<Value extends string>({
  label,
  value,
  options,
  disabled = false,
  className,
  tone = 'light',
  onChange,
}: DashboardJellySwitchProps<Value>) {
  const activeIndex = Math.max(
    0,
    options.findIndex((option) => option.value === value),
  );

  const [travel, setTravel] = useState<JellyTravel>({
    from: activeIndex,
    to: activeIndex,
    revision: 0,
  });

  const movement =
    travel.to === activeIndex
      ? travel
      : {
          from: activeIndex,
          to: activeIndex,
          revision: travel.revision,
        };

  const middle = movement.from + (movement.to - movement.from) * 0.72;

  const movingForward = movement.to >= movement.from;

  const style: JellySwitchStyle = {
    '--jelly-count': options.length,
    '--jelly-from': `${movement.from * 100}%`,
    '--jelly-middle': `${middle * 100}%`,
    '--jelly-to': `${movement.to * 100}%`,
  };

  const classes = ['dashboard-jelly-switch', `dashboard-jelly-switch--${tone}`, className]
    .filter(Boolean)
    .join(' ');

  return (
    <div className={classes} style={style} role="group" aria-label={label}>
      <span
        key={`${value}-${movement.revision}`}
        className={[
          'dashboard-jelly-switch__indicator',
          movement.revision > 0 ? 'is-moving' : '',
          movingForward ? 'is-forward' : 'is-backward',
        ]
          .filter(Boolean)
          .join(' ')}
        aria-hidden="true"
      />

      {options.map((option, index) => {
        const selected = option.value === value;
        const optionDisabled = disabled || option.disabled === true;

        return (
          <button
            type="button"
            aria-pressed={selected}
            disabled={optionDisabled}
            key={option.value}
            onClick={() => {
              if (selected || optionDisabled) {
                return;
              }

              setTravel((current) => ({
                from: activeIndex,
                to: index,
                revision: current.revision + 1,
              }));

              onChange(option.value);
            }}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
