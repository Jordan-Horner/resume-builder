export interface AssistantMessage { id: string; role: "user" | "assistant"; content: string }
export interface Proposal {
  id: string; status: string; message: string;
  payload: { resume_id: string; block_id: string; before: string; after: string; instruction: string };
}
export interface Conversation {
  id: string; resume_id: string | null; title: string; updated_at: string;
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
