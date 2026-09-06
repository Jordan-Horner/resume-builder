import { Component, createContext, lazy, Suspense, use, useCallback, useState, type ReactNode } from "react";
import "./assistant.css";

const AssistantPanel = lazy(() => import("./AssistantPanel"));
interface Context { discuss: (id: string, name: string) => void; discussJob: (id: string, name: string) => void }
const AssistantContext = createContext<Context>({ discuss: () => undefined, discussJob: () => undefined });
export function useAssistant() { return use(AssistantContext); }

class AssistantBoundary extends Component<{ children: ReactNode; onClose: () => void }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch() { console.error("Assistant interface failed to load."); }
  render() {
    return this.state.failed ? <aside className="assistant-panel" role="alert"><div className="assistant-intro"><h3>Assistant could not open</h3><p>Refresh the page to try again. Your workspace and saved conversations are unchanged.</p><button onClick={this.props.onClose}>Close assistant</button></div></aside> : this.props.children;
  }
}

export function AssistantProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [visited, setVisited] = useState(false);
  const [target, setTarget] = useState<{ kind: "resume" | "job"; id: string; name: string; nonce: number } | null>(null);
  const discuss = useCallback((id: string, name: string) => {
    setTarget({ kind: "resume", id, name, nonce: Date.now() }); setVisited(true); setOpen(true);
  }, []);
  const discussJob = useCallback((id: string, name: string) => {
    setTarget({ kind: "job", id, name, nonce: Date.now() }); setVisited(true); setOpen(true);
  }, []);
  return <AssistantContext value={{ discuss, discussJob }}>
    <div className={open ? "assistant-layout is-open" : "assistant-layout"}>
      <div className="assistant-workspace">{children}</div>
      {visited && <div className="assistant-dock" hidden={!open}>
        <AssistantBoundary onClose={() => setOpen(false)}>
        <Suspense fallback={<aside className="assistant-panel" role="status">Opening assistant…</aside>}>
          <AssistantPanel open={open} target={target} onClose={() => setOpen(false)} />
        </Suspense>
        </AssistantBoundary>
      </div>}
    </div>
    {!open && <button className="assistant-launcher" aria-expanded={false} onClick={() => { setVisited(true); setOpen(true); }}>Assistant</button>}
  </AssistantContext>;
}
