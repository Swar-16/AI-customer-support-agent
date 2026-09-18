// AI-customer-support-agent\apps\web\src\app\app.tsx
export function App() {
  return (
    <main className="foundation-screen" aria-labelledby="application-title">
      <section className="foundation-panel">
        <svg className="brand-spark" viewBox="0 0 48 48" aria-hidden="true" focusable="false">
          <path
            fill="currentColor"
            d="M24 2C27 17 31 21 46 24C31 27 27 31 24 46C21 31 17 27 2 24C17 21 21 17 24 2Z"
          />
        </svg>

        <p className="eyebrow">Support AI</p>
        <h1 id="application-title">A thoughtful space for support.</h1>
        <p className="supporting-copy">
          Customer conversations, support operations, and knowledge belong together.
        </p>

        <p className="integration-notice">
          Setup in progress. Sign-in and workspace connections are not available yet.
        </p>
      </section>
    </main>
  );
}
