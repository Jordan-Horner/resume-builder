import type { ReactNode } from "react";

export function SearchIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="11" cy="11" r="6.5" />
      <path d="m16 16 4 4" />
    </svg>
  );
}

export function ArrowIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  );
}

export function EmptyState({ title, children, actions }: { title: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <div className="empty-state">
      <div className="empty-state-copy"><h2>{title}</h2><div className="empty-state-content">{children}</div></div>
      {actions && <div className="empty-state-actions">{actions}</div>}
    </div>
  );
}

export function LoadingRows() {
  return (
    <div className="loading-rows" aria-label="Loading">
      {[0, 1, 2].map((row) => <div className="loading-row" key={row} />)}
    </div>
  );
}

export function ErrorMessage({ message, retry }: { message: string; retry: () => void }) {
  return (
    <div className="error-message" role="alert">
      <p>{message}</p>
      <button className="text-button" onClick={retry}>Try again</button>
    </div>
  );
}
