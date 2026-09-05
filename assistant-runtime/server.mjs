// Transport only: no provider credentials, workspace access, or application tools.
process.env.COPILOTKIT_TELEMETRY_DISABLED = "true";
process.env.DO_NOT_TRACK = "1";

const { CopilotRuntime, InMemoryAgentRunner, createCopilotRuntimeHandler } =
  await import("@copilotkit/runtime/v2");
const { HttpAgent } = await import("@ag-ui/client");

export function createHandler(agentUrl, token) {
  const runtime = new CopilotRuntime({
    agents: { default: new HttpAgent({ url: agentUrl, headers: { "x-assistant-token": token } }) },
    runner: new InMemoryAgentRunner({ maxThreads: 100, maxRunsPerThread: 2 }),
  });
  const handler = createCopilotRuntimeHandler({ runtime, activateChannels: false });
  return async (request) => {
    if (new URL(request.url).pathname === "/health") return Response.json({ status: "ok" });
    const response = await handler(request);
    if (!response.body) return response;
    // Runtime SSE can emit strings; standard Fetch consumers require byte chunks.
    const encoder = new TextEncoder();
    return new Response(response.body.pipeThrough(new TransformStream({
      transform(chunk, controller) { controller.enqueue(typeof chunk === "string" ? encoder.encode(chunk) : chunk); },
    })), { status: response.status, headers: response.headers });
  };
}

if (process.argv[1] && import.meta.url === new URL(process.argv[1], "file:").href) {
  const { serve } = await import("@hono/node-server");
  const token = process.env.RESUME_BUILDER_ASSISTANT_TOKEN;
  if (!token) throw new Error("Private assistant transport token is missing");
  const port = process.env.RESUME_BUILDER_PORTAL_PORT || "8765";
  const server = serve({
    hostname: "127.0.0.1", port: 8768,
    fetch: createHandler(`http://127.0.0.1:${port}/api/assistant/ag-ui`, token),
  });
  for (const signal of ["SIGTERM", "SIGINT"]) {
    process.on(signal, () => server.close(() => process.exit(0)));
  }
}
