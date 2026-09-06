export function UnavailableSetup({ name }: { name: string }) {
  return <div className="integration-setup integration-connected-copy"><strong>{name} can’t be configured from this page yet.</strong><p>This portal does not expose internal setup commands. Existing connections continue to work.</p></div>;
}
