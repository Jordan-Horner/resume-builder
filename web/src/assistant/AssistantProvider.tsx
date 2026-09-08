import { Component, createContext, lazy, Suspense, use, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import "./assistant.css";

const AssistantPanel = lazy(() => import("./AssistantPanel"));
export type AssistantWindowContext = { kind: "resume" | "job"; id: string; name: string };
interface Context {
  discuss: (id: string, name: string) => void;
  discussJob: (id: string, name: string, openingQuestion?: string) => void;
  setWindowContext: (context: AssistantWindowContext) => void;
}
const AssistantContext = createContext<Context>({ discuss: () => undefined, discussJob: () => undefined, setWindowContext: () => undefined });
export function useAssistant() { return use(AssistantContext); }

function useMobileAssistant() {
  const [mobile, setMobile] = useState(() => typeof window !== "undefined" && window.matchMedia?.("(max-width: 480px)").matches === true);
  useEffect(() => {
    const query = window.matchMedia?.("(max-width: 480px)");
    if (!query) return;
    const update = () => setMobile(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  return mobile;
}

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
  const [target, setTarget] = useState<{ kind: "resume" | "job"; id: string; name: string; openingQuestion?: string } | null>(null);
  const opener = useRef<HTMLElement | null>(null);
  const mobile = useMobileAssistant();
  const rememberOpener = useCallback(() => {
    if (document.activeElement instanceof HTMLElement) opener.current = document.activeElement;
  }, []);
  const close = useCallback(() => {
    setOpen(false);
    window.requestAnimationFrame(() => opener.current?.focus());
  }, []);
  const setWindowContext = useCallback((context: AssistantWindowContext) => {
    setTarget((current) => current?.kind === context.kind && current.id === context.id && current.name === context.name
      ? current
      : context);
  }, []);
  const discuss = useCallback((id: string, name: string) => {
    rememberOpener();
    setTarget({ kind: "resume", id, name }); setVisited(true); setOpen(true);
  }, [rememberOpener]);
  const discussJob = useCallback((id: string, name: string, openingQuestion?: string) => {
    rememberOpener();
    setTarget({ kind: "job", id, name, openingQuestion }); setVisited(true); setOpen(true);
  }, [rememberOpener]);
  const context = useMemo(() => ({ discuss, discussJob, setWindowContext }), [discuss, discussJob, setWindowContext]);
  return <AssistantContext value={context}>
    <div className={open ? "assistant-layout is-open" : "assistant-layout"}>
      <div className="assistant-workspace" inert={open && mobile ? true : undefined}>{children}</div>
      {visited && <div className="assistant-dock" id="career-assistant" hidden={!open}>
        <AssistantBoundary onClose={close}>
        <Suspense fallback={<aside className="assistant-panel" role="status">Opening assistant…</aside>}>
          <AssistantPanel open={open} modal={mobile} target={target} onClose={close} />
        </Suspense>
        </AssistantBoundary>
      </div>}
    </div>
    {!open && <button className="assistant-launcher" aria-controls="career-assistant" aria-expanded={false} onClick={(event) => { opener.current = event.currentTarget; setVisited(true); setOpen(true); }}>Assistant</button>}
  </AssistantContext>;
}
