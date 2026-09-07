export interface AssistantMessage { id: string; role: "user" | "assistant"; content: string }
export interface WordingProposalPayload { kind?: "wording"; resume_id: string; block_id: string; before: string; after: string; instruction: string }
export interface RemovalProposalPayload { kind: "resume_removal"; action?: "archive" | "retire"; resume_id: string; name: string; revision: string; application_references: { id: string; company: string; role: string }[]; vault_unchanged: true; tailored_resumes_unchanged: true }
export interface RestoreProposalPayload { kind: "resume_restore"; resume_id: string; name: string; revision: string }
export interface JobPreferenceProposalPayload { kind: "job_preference"; direction: "prefer" | "avoid"; action: "add" | "remove"; statement: string; confirmation_hash: string }
export interface Proposal { id: string; status: string; message: string; payload: WordingProposalPayload | RemovalProposalPayload | RestoreProposalPayload | JobPreferenceProposalPayload }
export interface Conversation {
  id: string; resume_id: string | null; job_id: string | null; context_name?: string; title: string; updated_at: string;
  messages: AssistantMessage[]; proposals: Proposal[];
  runs: { id: string; status: string }[];
}
export async function assistantRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/assistant${path}`, {
    ...init, headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (response.status === 204) return undefined as T;
  if (!response.headers.get("content-type")?.includes("application/json")) {
    throw new Error("Assistant unavailable. Please refresh the page or try again shortly.");
  }
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "The assistant request failed.");
  return data as T;
}
