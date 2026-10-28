import { useCallback, useEffect, useRef, useState } from "react";
import { api, getToken, setToken } from "./api";
import Chat from "./Chat.jsx";

function AuthScreen({ onAuth }) {
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const path = mode === "login" ? "/auth/login" : "/auth/register";
      const data = await api(path, { method: "POST", body: { email, password } });
      setToken(data.token);
      onAuth(data.email);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth">
      <section className="auth-hero" aria-hidden="true">
        <p className="hero-quote">
          The contract renews automatically unless either party gives{" "}
          <mark>sixty days' written notice</mark>
          <sup className="cite on">1</sup> before the end of the term.
        </p>
        <p className="hero-note">Every answer points to the passage it came from.</p>
      </section>

      <form className="auth-form" onSubmit={submit}>
        <h1>Marginalia</h1>
        <p className="sub">Upload your PDFs and notes, then ask questions in plain language.</p>

        <label>
          Email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" required />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            minLength={8}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            required
          />
        </label>
        {mode === "register" && <p className="hint">Use at least 8 characters.</p>}
        {error && <p className="error" role="alert">{error}</p>}

        <button className="primary" disabled={busy}>
          {busy ? "Working…" : mode === "login" ? "Sign in" : "Create account"}
        </button>
        <button type="button" className="link" onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(""); }}>
          {mode === "login" ? "New here? Create an account" : "Have an account? Sign in"}
        </button>
      </form>
    </main>
  );
}

function Library({ docs, selected, setSelected, onUpload, onDelete, uploading, error, email, onSignOut }) {
  const fileRef = useRef(null);
  const toggle = (id) =>
    setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));

  return (
    <aside className="library">
      <div className="lib-head">
        <h1>Marginalia</h1>
        <p className="muted">{email}</p>
      </div>

      <button className="primary" onClick={() => fileRef.current.click()} disabled={uploading}>
        {uploading ? "Reading document…" : "Add a document"}
      </button>
      <input
        ref={fileRef}
        type="file"
        accept=".pdf,.txt,.md"
        hidden
        onChange={(e) => { if (e.target.files[0]) onUpload(e.target.files[0]); e.target.value = ""; }}
      />
      <p className="hint">PDF, TXT or Markdown, up to 10 MB.</p>
      {error && <p className="error" role="alert">{error}</p>}

      <h2>Your documents</h2>
      {docs.length === 0 ? (
        <p className="muted">Nothing here yet. Add a document to start asking questions.</p>
      ) : (
        <>
          <p className="hint">
            {selected.length === 0 ? "Searching all documents." : `Searching ${selected.length} selected.`}
          </p>
          <ul className="docs">
            {docs.map((d) => (
              <li key={d.id}>
                <label>
                  <input type="checkbox" checked={selected.includes(d.id)} onChange={() => toggle(d.id)} />
                  <span className="doc-name" title={d.filename}>{d.filename}</span>
                </label>
                <button className="icon" onClick={() => onDelete(d)} aria-label={`Delete ${d.filename}`}>×</button>
              </li>
            ))}
          </ul>
        </>
      )}

      <button className="link signout" onClick={onSignOut}>Sign out</button>
    </aside>
  );
}

export default function App() {
  const [email, setEmail] = useState(null);
  const [checking, setChecking] = useState(!!getToken());
  const [docs, setDocs] = useState([]);
  const [selected, setSelected] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");

  const signOut = useCallback(() => { setToken(null); setEmail(null); setDocs([]); setSelected([]); }, []);

  useEffect(() => {
    window.addEventListener("signout", signOut);
    return () => window.removeEventListener("signout", signOut);
  }, [signOut]);

  useEffect(() => {
    if (!getToken()) return;
    api("/me").then((u) => setEmail(u.email)).catch(() => {}).finally(() => setChecking(false));
  }, []);

  const loadDocs = useCallback(() => api("/documents").then(setDocs).catch((e) => setError(e.message)), []);
  useEffect(() => { if (email) loadDocs(); }, [email, loadDocs]);

  async function upload(file) {
    setUploading(true);
    setError("");
    try {
      const form = new FormData();
      form.append("file", file);
      await api("/documents", { method: "POST", form });
      await loadDocs();
    } catch (e) {
      setError(e.message);
    } finally {
      setUploading(false);
    }
  }

  async function remove(doc) {
    if (!window.confirm(`Delete "${doc.filename}"? This removes it from search.`)) return;
    try {
      await api(`/documents/${doc.id}`, { method: "DELETE" });
      setSelected((s) => s.filter((x) => x !== doc.id));
      await loadDocs();
    } catch (e) {
      setError(e.message);
    }
  }

  if (checking) return <div className="loading">Loading…</div>;
  if (!email) return <AuthScreen onAuth={setEmail} />;

  return (
    <div className="shell">
      <Library
        docs={docs} selected={selected} setSelected={setSelected}
        onUpload={upload} onDelete={remove} uploading={uploading}
        error={error} email={email} onSignOut={signOut}
      />
      <Chat docs={docs} selected={selected} />
    </div>
  );
}
