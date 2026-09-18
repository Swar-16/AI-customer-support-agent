// apps/web/src/features/chat/saved-response-rating.test.tsx
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { SavedResponseRating } from './saved-response-rating';

afterEach(cleanup);

describe('saved response rating', () => {
  it.each([1, 2, 3, 4, 5])('renders the stored rating %i without submission controls', (rating) => {
    render(<SavedResponseRating rating={rating} />);

    expect(screen.getByRole('region', { name: 'Saved response rating' })).toBeInTheDocument();

    expect(screen.getByText(`Your rating: ${rating} out of 5. Thank you.`)).toBeInTheDocument();

    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(screen.queryByRole('radio')).not.toBeInTheDocument();
  });

  it.each([0, 6, 2.5, Number.NaN])('does not present an invalid rating %s', (rating) => {
    render(<SavedResponseRating rating={rating} />);

    expect(screen.queryByRole('region', { name: 'Saved response rating' })).not.toBeInTheDocument();
  });
});
