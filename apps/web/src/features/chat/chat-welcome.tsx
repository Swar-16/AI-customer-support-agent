// apps/web/src/features/chat/chat-welcome.tsx
import { useState } from 'react';
import { Pause, Play } from 'lucide-react';

export function ChatWelcome() {
  const [paused, setPaused] = useState(false);

  return (
    <section className="chat-welcome" aria-labelledby="chat-welcome-title">
      <div className="chat-welcome__copy">
        <p className="chat-welcome__eyebrow">A space for your questions</p>
        <h2 id="chat-welcome-title">
          {'A little clarity, '}
          <br />
          when you need it.
        </h2>
        <p className="chat-welcome__description">
          Create a conversation or open one from your history. We’ll take it from there.
        </p>
        <div className="chat-welcome__hint">
          <span aria-hidden="true">✦</span>
          <p>Start with what’s on your mind. A few details help.</p>
        </div>
      </div>

      <div className="chat-welcome__visual" data-paused={paused ? 'true' : 'false'}>
        <div className="chat-welcome__sky" aria-hidden="true">
          <div className="chat-welcome__halo" />

          <svg className="chat-welcome__spark" viewBox="0 0 100 100" focusable="false">
            <path
              d="M50 5C56 34 66 44 95 50C66 56 56 66 50 95C44 66 34 56 5 50C34 44 44 34 50 5Z"
              fill="currentColor"
            />
          </svg>

          {[0, 1, 2, 3, 4].map((index) => (
            <span key={index} className={`chat-welcome__meteor chat-welcome__meteor--${index}`}>
              <span>✦</span>
            </span>
          ))}
        </div>

        <button
          type="button"
          className="chat-welcome__motion"
          aria-label="Pause welcome animation"
          aria-pressed={paused}
          onClick={() => setPaused((value) => !value)}
        >
          {paused ? <Play size={15} aria-hidden="true" /> : <Pause size={15} aria-hidden="true" />}
          <span>{paused ? 'Resume animation' : 'Pause animation'}</span>
        </button>
      </div>
    </section>
  );
}
