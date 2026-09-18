// apps/web/src/features/chat/saved-response-rating.tsx
import { Star } from 'lucide-react';

import './saved-response-rating.css';

interface SavedResponseRatingProps {
  readonly rating: number;
}

export function SavedResponseRating({ rating }: SavedResponseRatingProps) {
  if (!Number.isInteger(rating) || rating < 1 || rating > 5) {
    return null;
  }

  return (
    <section className="saved-response-rating" aria-label="Saved response rating">
      <div className="saved-response-rating__stars" aria-hidden="true">
        {[1, 2, 3, 4, 5].map((value) => (
          <Star
            key={value}
            size={21}
            fill={value <= rating ? 'currentColor' : 'none'}
            strokeWidth={1.7}
          />
        ))}
      </div>

      <p>Your rating: {rating} out of 5. Thank you.</p>
    </section>
  );
}
