import assert from "node:assert/strict";
import test from "node:test";
import { createServer } from "node:http";
import { createHandler } from "./server.mjs";

test("production runtime discovers our Python agent without vendor credentials", async () => {
  assert.equal(process.env.COPILOTKIT_LICENSE_TOKEN, undefined);
  const handler = createHandler("http://127.0.0.1:9/api/assistant/ag-ui", "fixture-only");
  const response = await handler(new Request("http://localhost/info"));
  assert.equal(response.status, 200);
  const info = await response.json();
  assert.ok(info.agents.default);
  assert.equal((await handler(new Request("http://localhost/health"))).status, 200);
});

test("production runtime forwards a run to Python and returns its saved messages", async () => {
  let received;
  const upstream = createServer(async (req, res) => {
    assert.equal(req.headers["x-assistant-token"], "fixture-only");
    let body = "";
    for await (const chunk of req) body += chunk;
    received = JSON.parse(body);
    res.writeHead(200, { "Content-Type": "text/event-stream" });
    for (const event of [
      { type: "RUN_STARTED", threadId: received.threadId, runId: received.runId },
      { type: "MESSAGES_SNAPSHOT", messages: [{ id: "reply", role: "assistant", content: "Fixture response" }] },
      { type: "RUN_FINISHED", threadId: received.threadId, runId: received.runId },
    ]) res.write(`data: ${JSON.stringify(event)}\n\n`);
    res.end();
  });
  await new Promise((resolve) => upstream.listen(0, "127.0.0.1", resolve));
  try {
    const handler = createHandler(`http://127.0.0.1:${upstream.address().port}/ag-ui`, "fixture-only");
    const response = await handler(new Request("http://localhost/agent/default/run", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ threadId: "fixture-thread", runId: "fixture-run", messages: [{ id: "user", role: "user", content: "Hello" }], tools: [], context: [], state: {}, forwardedProps: {} }),
    }));
    assert.equal(response.status, 200);
    assert.match(await response.text(), /Fixture response/);
    assert.equal(received.threadId, "fixture-thread");
  } finally { await new Promise((resolve) => upstream.close(resolve)); }
});
