// apps/web/src/features/auth/login-atmosphere.tsx
import { useEffect, useState } from 'react';

const illustrations = [
  'images/auth/support-team.jpg',
  'images/auth/agent-assistance.jpg',
  'images/auth/agent-center.jpg',
  'images/auth/support-agent.jpg',
] as const;

export function LoginAtmosphere() {
  const [activeIndex, setActiveIndex] = useState(0);
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    if (paused || illustrations.length < 2 || typeof window.matchMedia !== 'function') return;

    const preference = window.matchMedia('(prefers-reduced-motion: reduce)');

    let intervalId: number | undefined;

    function stop() {
      if (intervalId !== undefined) {
        window.clearInterval(intervalId);
        intervalId = undefined;
      }
    }

    function synchronize() {
      stop();

      if (!preference.matches && !document.hidden) {
        intervalId = window.setInterval(() => {
          setActiveIndex((index) => (index + 1) % illustrations.length);
        }, 8000);
      }
    }

    synchronize();
    preference.addEventListener('change', synchronize);
    document.addEventListener('visibilitychange', synchronize);

    return () => {
      stop();
      preference.removeEventListener('change', synchronize);
      document.removeEventListener('visibilitychange', synchronize);
    };
  }, [paused]);

  return (
    <div className="login-atmosphere" data-paused={paused ? 'true' : 'false'}>
      <div className="login-atmosphere__art" aria-hidden="true">
        {(['left', 'right'] as const).map((position, positionIndex) => {
          const visibleIndex = (activeIndex + positionIndex) % illustrations.length;

          return (
            <div
              key={position}
              className={`login-atmosphere__scene login-atmosphere__scene--${position}`}
            >
              {illustrations.map((path, index) => (
                <img
                  key={path}
                  className="login-atmosphere__image"
                  data-active={index === visibleIndex ? 'true' : 'false'}
                  src={`${import.meta.env.BASE_URL}${path}`}
                  alt=""
                  draggable={false}
                  decoding="async"
                />
              ))}
            </div>
          );
        })}
      </div>

      <button
        className="login-atmosphere__toggle"
        type="button"
        aria-label="Pause background animation"
        aria-pressed={paused}
        onClick={() => setPaused((value) => !value)}
      >
        <span aria-hidden="true">{paused ? '▶' : 'Ⅱ'}</span>
        {paused ? 'Resume background' : 'Pause background'}
      </button>
    </div>
  );
}
