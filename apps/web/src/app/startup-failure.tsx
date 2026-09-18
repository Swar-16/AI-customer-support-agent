// apps/web/src/app/startup-failure.tsx

interface StartupFailureProps {
  readonly reason: 'configuration' | 'startup';
}

export function StartupFailure({ reason }: StartupFailureProps) {
  return (
    <main className="foundation-screen" aria-labelledby="startup-title">
      <section className="foundation-panel">
        <p className="eyebrow">Support AI</p>

        <h1 id="startup-title">Support AI could not start.</h1>

        <p className="supporting-copy" role="alert">
          {reason === 'configuration'
            ? 'The application connection settings are invalid. Contact the person managing this deployment.'
            : 'The application could not initialize in this browser. Use an up-to-date browser and contact support if the problem continues.'}
        </p>

        <p className="integration-notice">Sign-in and workspaces are unavailable.</p>
      </section>
    </main>
  );
}
