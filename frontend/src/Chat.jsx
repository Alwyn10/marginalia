import { useEffect, useRef, useState } from "react";
import { api } from "./api";

/** Renders answer text with [n] markers turned into buttons that open the source. */
function AnswerText({ text, sources, open, onOpen }) {
  return (
    <p className="answer">
      {text.split(/(\[\d+\])/g).map((part, i) => {
        const m = part.match(/^\[(\d+)\]$/);
        const n = m ? Number(m[1]) : null;
        if (!n || !sources[n - 1]) return <span key={i}>{part}</span>;
        return (
          <button
            key={i}
            className={"cite" + (open === n ? " on" : "")}
            onClick={() => onOpen(open === n ? null : n)}
            aria-label={`Source ${n}: ${sources[n - 1].filename}, page ${sources[n - 1].page}`}
            aria-expanded={open === n}
          >
            {n}
          </button>
        );
      })}
    </p>
  );
}

function Message({ msg }) {
  const [open, setOpen] = useState(null);

  if (msg.role === "user") return <div className="msg user">{msg.content}</div>;

  const sources = msg.sources || [];
  const fromOpening = sources.length > 0 && sources[0].score == null;
  return (
    <div className="msg assistant">
      <AnswerText text={msg.content} sources={sources} open={open} onOpen={setOpen} />
      {fromOpening && (
        <p className="note">
          This was a broad question, so the answer comes from the opening of your document instead of a search.
          Ask about something specific for a more precise answer.
        </p>
      )}
      {sources.length > 0 && (
        <ul className="sources">
          {sources.map((s, i) => (
            <li key={i}>
              <button className="source-row" onClick={() => setOpen(open === i + 1 ? null : i + 1)} aria-expanded={open === i + 1}>
                <span className={"cite" + (open === i + 1 ? " on" : "")}>{i + 1}</span>
                <span className="source-name">{s.filename}, page {s.page}</span>
                <span className="match">{s.score == null ? "opening passage" : `${Math.round(s.score * 100)}% match`}</span>
              </button>
              {open === i + 1 && (
                <blockquote className="passage"><mark>{s.text}</mark></blockquote>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function Chat({ docs, selected }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const endRef = useRef(null);

  useEffect(() => {
    api("/history").then(setMessages).catch(() => {});
  }, []);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [messages, busy]);

  async function send(e) {
    e?.preventDefault();
    const question = input.trim();
    if (!question || busy) return;
    setInput("");
    setError("");
    setBusy(true);
    setMessages((m) => [...m, { role: "user", content: question }]);
    try {
      const data = await api("/chat", { method: "POST", body: { question, doc_ids: selected } });
      setMessages((m) => [...m, { role: "assistant", content: data.answer, sources: data.sources }]);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function clear() {
    if (!window.confirm("Clear this conversation?")) return;
    await api("/history", { method: "DELETE" });
    setMessages([]);
  }

  const noDocs = docs.length === 0;

  return (
    <main className="chat">
      <header className="chat-head">
        <span className="muted">
          {noDocs ? "No documents yet" : selected.length ? `Asking ${selected.length} of ${docs.length} documents` : `Asking all ${docs.length} documents`}
        </span>
        {messages.length > 0 && <button className="link" onClick={clear}>Clear conversation</button>}
      </header>

      <div className="thread" aria-live="polite">
        {messages.length === 0 && (
          <div className="empty">
            <h2>{noDocs ? "Add a document to begin." : "What do you want to know?"}</h2>
            <p>
              {noDocs
                ? "Upload a PDF, report or notes from the library. Answers will cite the exact passages they came from."
                : "Ask about a clause, a figure or a finding. Select the numbered markers in an answer to read the original passage."}
            </p>
          </div>
        )}
        {messages.map((m, i) => <Message key={i} msg={m} />)}
        {busy && <div className="msg assistant muted">Reading your documents…</div>}
        {error && <p className="error" role="alert">{error}</p>}
        <div ref={endRef} />
      </div>

      <form className="composer" onSubmit={send}>
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) send(e); }}
          placeholder={noDocs ? "Add a document first" : "Ask a question about your documents"}
          rows={2}
          disabled={noDocs}
          aria-label="Your question"
        />
        <button className="primary" disabled={busy || noDocs || !input.trim()}>Ask</button>
      </form>
    </main>
  );
}
