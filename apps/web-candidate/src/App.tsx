export default function App() {
  return (
    <div className="shell">
      <header className="topbar">
        <span className="wordmark">AIVA</span>
        <span className="surface-label">Candidate Journey</span>
      </header>
      <main className="content">
        <section className="empty-state" aria-labelledby="empty-heading">
          <h1 id="empty-heading">Your invitation opens here</h1>
          <p>
            When a hiring team invites you, your personal link opens this portal with
            your questionnaire and interview. Nothing to do right now — and nothing
            about you is stored until you are invited.
          </p>
        </section>
      </main>
    </div>
  );
}
