// apps/web/src/features/chat/agent-working.tsx
import './outgoing-turn.css';

export function AgentWorking({ label = 'Working on your response…' }: { readonly label?: string }) {
  return (
    <div className="agent-working" role="status" aria-live="polite" aria-atomic="true">
      <span className="agent-working__scene" aria-hidden="true">
        <svg viewBox="0 0 80 80" focusable="false">
          <ellipse className="agent-working__shadow" cx="40" cy="67" rx="18" ry="4" />
          <g className="agent-working__robot">
            <path className="agent-working__antenna" d="M40 25V15" />
            <circle className="agent-working__signal" cx="40" cy="12" r="4" />
            <rect className="agent-working__ear" x="13" y="35" width="8" height="15" rx="4" />
            <rect className="agent-working__ear" x="59" y="35" width="8" height="15" rx="4" />
            <rect className="agent-working__head" x="19" y="25" width="42" height="36" rx="13" />
            <rect className="agent-working__face" x="25" y="33" width="30" height="18" rx="7" />
            <g className="agent-working__eyes">
              <rect x="31" y="39" width="4" height="6" rx="2" />
              <rect x="45" y="39" width="4" height="6" rx="2" />
            </g>
            <path className="agent-working__smile" d="M36 55Q40 58 44 55" />
          </g>
          <g className="agent-working__spark">
            <path d="M65 10L67 15L72 17L67 19L65 24L63 19L58 17L63 15Z" />
          </g>
        </svg>
      </span>
      <span className="agent-working__label">{label}</span>
    </div>
  );
}
