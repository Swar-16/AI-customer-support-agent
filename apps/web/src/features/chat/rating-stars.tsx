// apps/web/src/features/chat/rating-stars.tsx
import { useState } from 'react';
import type { Ref } from 'react';
import { Star } from 'lucide-react';

interface RatingStarsProps {
  readonly name: string;
  readonly value: number | null;
  readonly disabled: boolean;
  readonly invalid: boolean;
  readonly describedBy: string;
  readonly inputRef: Ref<HTMLInputElement>;
  readonly onChange: (value: number) => void;
  readonly onBlur: () => void;
}

const choices = [
  { value: 1, word: 'Poor' },
  { value: 2, word: 'Fair' },
  { value: 3, word: 'Okay' },
  { value: 4, word: 'Good' },
  { value: 5, word: 'Excellent' },
] as const;

export function RatingStars({
  name,
  value,
  disabled,
  invalid,
  describedBy,
  inputRef,
  onChange,
  onBlur,
}: RatingStarsProps) {
  const [hovered, setHovered] = useState<number | null>(null);
  const [focused, setFocused] = useState<number | null>(null);

  const preview = disabled ? null : (hovered ?? focused);
  const displayed = preview ?? value ?? 0;
  const word = choices.find((choice) => choice.value === displayed)?.word ?? 'Choose a rating';

  return (
    <div className="rating-stars">
      <div
        className="rating-stars__choices"
        onPointerLeave={() => setHovered(null)}
        onPointerCancel={() => setHovered(null)}
      >
        {choices.map((choice, index) => {
          const animated = preview === choice.value;

          return (
            <label
              key={choice.value}
              className="rating-stars__choice"
              data-lit={choice.value <= displayed}
              data-mood={animated ? choice.value : undefined}
              data-disabled={disabled}
              onPointerEnter={(event) => {
                if (!disabled && event.pointerType !== 'touch') {
                  setHovered(choice.value);
                }
              }}
            >
              <input
                ref={index === 0 ? inputRef : undefined}
                className="rating-stars__input"
                type="radio"
                name={name}
                value={choice.value}
                checked={value === choice.value}
                disabled={disabled}
                aria-label={`${choice.value} — ${choice.word}`}
                aria-invalid={invalid}
                aria-describedby={describedBy}
                onChange={() => onChange(choice.value)}
                onFocus={() => {
                  if (!disabled) setFocused(choice.value);
                }}
                onBlur={() => {
                  setFocused(null);
                  onBlur();
                }}
              />

              <span className="rating-stars__surface" aria-hidden="true">
                <Star className="rating-stars__icon" size={28} strokeWidth={1.7} />

                {animated && choice.value === 5 && (
                  <span className="rating-stars__confetti">
                    <i />
                    <i />
                    <i />
                    <i />
                    <i />
                    <i />
                  </span>
                )}
              </span>
            </label>
          );
        })}
      </div>

      {/* The radio's accessible name already announces the rating. */}
      <span className="rating-stars__word" aria-hidden="true">
        {word}
      </span>
    </div>
  );
}
