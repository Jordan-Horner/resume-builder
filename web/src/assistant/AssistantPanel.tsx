import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { assistantRequest, type Conversation, type Proposal } from "./api";

interface Props { open: boolean; modal?: boolean; target: { kind: "resume" | "job"; id: string; name: string; nonce: number; openingQuestion?: string } | null; onClose: () => void }

function ProposalView({ proposal, decide }: { proposal: Proposal; decide: (id: string, action: string) => void }) {
  if (proposal.payload.kind === "job_preference") {
    const adding = proposal.payload.action === "add";
    const avoiding = proposal.payload.direction === "avoid";
    return <section className="assistant-proposal" aria-label="Proposed job preference">
      <strong>{adding ? avoiding ? "Avoid this kind of work?" : "Prefer this kind of work?" : "Remove this preference?"}</strong>
      <p>{proposal.payload.statement}</p>
      <small>This shapes future quick screens. It does not affect whether you are qualified.</small>
      {proposal.status === "pending" ? <div className="assistant-actions">
        <button className="primary-button" onClick={() => decide(proposal.id, "accept")}>{adding ? "Save preference" : "Remove preference"}</button>
        <button className="text-button" onClick={() => decide(proposal.id, "decline")}>Cancel</button>
      </div> : <p role="status">{proposal.status === "applying" ? "Saving preference…" : proposal.message}</p>}
    </section>;
  }
  if (proposal.payload.kind === "resume_removal") {
    const retiring = proposal.payload.action === "retire" || proposal.payload.application_references.length > 0;
    return <section className="assistant-proposal assistant-removal" aria-label="Proposed resume removal">
    <strong>{retiring ? "Retire this directional résumé?" : "Remove this directional résumé?"}</strong>
    <p>{retiring ? `It will leave future matching but ${proposal.payload.application_references.length} application ${proposal.payload.application_references.length === 1 ? "copy" : "copies"} will remain available.` : "It will stop appearing in Resumes and future matching."} Career-vault evidence and tailored résumés stay unchanged.</p>
    {proposal.status === "pending" ? <div className="assistant-actions">
      <button className="danger-button" onClick={() => decide(proposal.id, "accept")}>{retiring ? "Retire résumé" : "Remove résumé"}</button>
      <button className="text-button" onClick={() => decide(proposal.id, "decline")}>Keep résumé</button>
    </div> : <p role="status">{proposal.status === "applying" ? `${retiring ? "Retiring" : "Removing"} résumé…` : proposal.message}</p>}
  </section>;
  }
  if (proposal.payload.kind === "resume_restore") return <section className="assistant-proposal" aria-label="Proposed resume restoration">
    <strong>Restore this directional résumé?</strong>
    <p>It will return to the active library and may be recommended for future jobs.</p>
    {proposal.status === "pending" ? <div className="assistant-actions">
      <button className="primary-button" onClick={() => decide(proposal.id, "accept")}>Restore résumé</button>
      <button className="text-button" onClick={() => decide(proposal.id, "decline")}>Keep retired</button>
    </div> : <p role="status">{proposal.status === "applying" ? "Restoring résumé…" : proposal.message}</p>}
  </section>;
  return <section className="assistant-proposal" aria-label="Proposed resume change">
    <strong>Suggested wording</strong>
    <small>Current</small><p>{proposal.payload.before}</p>
    <small>Proposed</small><p>{proposal.payload.after}</p>
    {proposal.status === "pending" ? <div className="assistant-actions">
      <button className="primary-button" onClick={() => decide(proposal.id, "accept")}>Use this wording</button>
      <button className="text-button" onClick={() => decide(proposal.id, "decline")}>Keep current</button>
    </div> : <p role="status">{proposal.status === "applying" ? "Applying and reviewing…" : proposal.message}</p>}
    {proposal.status === "applied" && <a href={`/api/resume-preview?resume_id=${encodeURIComponent(proposal.payload.resume_id)}`} target="_blank" rel="noreferrer">View updated résumé ↗</a>}
  </section>;
}

function ConversationView({ initial, changed, open }: { initial: Conversation; changed: (thread: Conversation) => void; open: boolean }) {
  const [thread, setThread] = useState(initial);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const end = useRef<HTMLDivElement>(null);
  const submitting = useRef(false);
  const stopAllowedAt = useRef(0);
  const running = sending || thread.runs.some((run) => run.status === "running");

  useEffect(() => {
    if (!open || document.hidden) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await assistantRequest<Conversation>(`/threads/${initial.id}`);
        if (!active) return;
        setThread(next); changed(next);
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "Could not restore conversation.");
      }
      if (active) timer = setTimeout(poll, running ? 1500 : 10000);
    };
    timer = setTimeout(poll, running ? 1500 : 10000);
    return () => { active = false; clearTimeout(timer); };
  }, [initial.id, changed, open, running]);

  useEffect(() => { end.current?.scrollIntoView?.({ block: "nearest" }); }, [thread.messages.length, sending]);

  async function send() {
    if (!input.trim() || running || submitting.current) return;
    submitting.current = true;
    stopAllowedAt.current = Date.now() + 750;
    const content = input.trim();
    setError(""); setSending(true); setInput("");
    try {
      // getRandomValues also works on self-hosted HTTP LAN origins; randomUUID does not.
      const id = Array.from(crypto.getRandomValues(new Uint8Array(16)), (byte) => byte.toString(16).padStart(2, "0")).join("");
      setThread((current) => ({ ...current, messages: [...current.messages, { id, role: "user", content }] }));
      const next = await assistantRequest<Conversation>(`/threads/${initial.id}/runs`, {
        method: "POST",
        body: JSON.stringify({ run_id: id, prompt: content }),
      });
      setThread(next); changed(next);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not send message.");
      setInput(content);
    } finally { submitting.current = false; setSending(false); }
  }

  async function stop() {
    // Ignore the second click of a double-click after Send changes into Stop.
    if (Date.now() < stopAllowedAt.current) return;
    try {
      await assistantRequest(`/threads/${initial.id}/stop`, { method: "POST" });
      submitting.current = false;
      setSending(false);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not stop response."); }
  }

  async function decide(id: string, action: string) {
    setError("");
    try {
      const next = await assistantRequest<Conversation>(`/threads/${initial.id}/proposals/${id}/${action}`, { method: "POST" });
      setThread(next); changed(next);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not save your decision."); }
  }

  return <>
    <div className="assistant-transcript" aria-label="Conversation">
      {!thread.messages.length && <div className="assistant-intro"><h3>What would you like to work on?</h3><p>{thread.resume_id ? "Ask about this résumé, revise it, or remove it from active use." : thread.job_id ? "Ask me to screen this job or explain its fit." : "Ask about your job queue, or attach a job or directional résumé."}</p></div>}
      {thread.messages.map((message) => <div className={`assistant-message ${message.role}`} key={message.id}>
        <small>{message.role === "user" ? "You" : "Assistant"}</small>
        <div className="assistant-markdown"><ReactMarkdown skipHtml>{message.content}</ReactMarkdown></div>
      </div>)}
      {thread.proposals.map((proposal) => <ProposalView key={proposal.id} proposal={proposal} decide={decide} />)}
      {running && <p className="assistant-progress" role="status">Working with your career workspace…</p>}
      <div ref={end} />
    </div>
    <form className="assistant-composer" onSubmit={(event) => { event.preventDefault(); void send(); }}>
      {error && <p className="error-text" role="alert">{error}</p>}
      <label className="sr-only" htmlFor="assistant-message">Message the assistant</label>
      <textarea id="assistant-message" value={input} maxLength={12000} placeholder="Ask about your résumé…" rows={3} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => {
        if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send(); }
      }} />
      <div className="assistant-compose-footer"><small>Changes stay in your control</small>{running ? <button className="secondary-button" type="button" onClick={() => void stop()}>Stop</button> : <button className="primary-button" disabled={!input.trim()}>Send</button>}</div>
    </form>
  </>;
}

export default function AssistantPanel({ open, modal = false, target, onClose }: Props) {
  const [thread, setThread] = useState<Conversation | null>(null);
  const [threads, setThreads] = useState<Conversation[]>([]);
  const [history, setHistory] = useState(false);
  const [status, setStatus] = useState<{ configured: boolean; online: boolean } | null>(null);
  const [error, setError] = useState("");
  const header = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLElement>(null);
  const observedTarget = useRef<number | null>(null);
  const active = useRef<Conversation | null>(null);
  const update = useRef((next: Conversation) => { active.current = next; setThread(next); }).current;

  async function select(id: string) {
    const next = await assistantRequest<Conversation>(`/threads/${id}`);
    setThread(next); active.current = next; setHistory(false);
    try { localStorage.setItem("resume-builder.assistant.v1", id); } catch { console.warn("Assistant history preference could not be saved; server history remains available."); }
  }
  async function start(context?: { kind: "resume" | "job"; id: string }) {
    try {
      const body = context?.kind === "job" ? { job_id: context.id } : { resume_id: context?.id ?? null };
      const next = await assistantRequest<Conversation>("/threads", { method: "POST", body: JSON.stringify(body) });
      await select(next.id);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not start conversation."); }
  }
  async function refresh() {
    try {
      const [health, list] = await Promise.all([
        assistantRequest<{ configured: boolean; online: boolean }>("/status"),
        assistantRequest<{ threads: Conversation[] }>("/threads"),
      ]);
      setStatus(health); setThreads(list.threads); setError("");
      if (!active.current) {
        let saved: string | null = null;
        try { saved = localStorage.getItem("resume-builder.assistant.v1"); } catch { console.warn("Assistant history preference unavailable; use History to reopen a conversation."); }
        const previous = list.threads.find((item) => item.id === saved);
        if (previous) await select(previous.id); else await start();
      }
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not open assistant."); }
  }
  useEffect(() => { void refresh(); }, []);
  useEffect(() => { if (open) header.current?.focus(); }, [open]);
  const busy = active.current?.runs.some((run) => run.status === "running") || active.current?.proposals.some((proposal) => proposal.status === "applying");
  const activeTargetId = target?.kind === "job" ? thread?.job_id : thread?.resume_id;
  const pendingTarget = target && observedTarget.current !== target.nonce && target.id !== activeTargetId;

  function handlePanelKeyDown(event: React.KeyboardEvent<HTMLElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (!modal || event.key !== "Tab") return;
    const focusable = Array.from(panel.current?.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ) || []).filter((element) => !element.hidden);
    const first = focusable[0];
    const last = focusable.at(-1);
    if (!first || !last) return;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault(); last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault(); first.focus();
    }
  }

  return <aside ref={panel} className="assistant-panel" role={modal ? "dialog" : undefined} aria-modal={modal ? true : undefined} aria-label="Career assistant" onKeyDown={handlePanelKeyDown}>
    <header className="assistant-header"><strong>Assistant</strong><div>
      <button className="text-button" disabled={busy} onClick={() => { setHistory(!history); void refresh(); }}>History</button>
      <button className="text-button" disabled={busy} onClick={() => void start()}>New</button>
      <button ref={header} className="assistant-close" aria-label="Close assistant" onClick={onClose}>×</button>
    </div></header>
    {pendingTarget && <div className="assistant-context assistant-context-question"><span>{target.openingQuestion || target.name}</span><button className="text-button" disabled={busy} onClick={() => { observedTarget.current = target.nonce; void start({ kind: target.kind, id: target.id }); }}>{target.openingQuestion ? "Answer" : target.kind === "job" ? "Discuss this job" : "Discuss this résumé"}</button></div>}
    {thread?.resume_id && <div className="assistant-context"><small>Working on</small><span>{thread.resume_id.split("/").pop()?.replace(/\.md$/, "").replaceAll("-", " ")}</span></div>}
    {thread?.job_id && <div className="assistant-context"><small>Working on job</small><span>{thread.context_name || thread.job_id}</span></div>}
    {error && <div className="assistant-context" role="alert">{error}<button className="text-button" onClick={() => void refresh()}>Retry</button></div>}
    {history ? <div className="assistant-history">{threads.map((item) => <button key={item.id} onClick={() => { select(item.id).catch((reason: Error) => setError(reason.message)); }}>{item.title}<small>{new Date(item.updated_at).toLocaleDateString()}</small></button>)}</div>
      : !status ? <p className="assistant-context" role="status">Connecting…</p>
      : !status.configured ? <div className="assistant-intro"><h3>Connect your AI provider</h3><p>The assistant uses your existing model settings.</p><a href="/settings/integrations">Configure AI →</a><button className="text-button" onClick={() => void refresh()}>Check again</button></div>
      : !status.online ? <div className="assistant-intro"><h3>Assistant temporarily unavailable</h3><p>Your workspace is still available. Try reconnecting shortly.</p><button className="secondary-button" onClick={() => void refresh()}>Reconnect</button></div>
      : thread && <ConversationView key={thread.id} initial={thread} changed={update} open={open} />}
  </aside>;
}
