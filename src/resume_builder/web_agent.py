"""Same-origin web assistant routes and a private AG-UI bridge."""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from .agent_config import DEFAULT_AGENT_CONFIG
from .agent_state import default_agent_state_path
from .web_agent_resume import resume_path
from .web_agent_state import WebAgentState
from .web_service import DashboardService


def install_assistant(app: FastAPI, workspace: Path) -> None:
    router = APIRouter(prefix="/api/assistant")
    # Initialize lazily: merely serving unrelated portal routes must not create private state.
    state: WebAgentState | None = None
    processes: dict[str, asyncio.subprocess.Process] = {}
    tasks: set[asyncio.Task[None]] = set()
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> Any:
        async with original_lifespan(application):
            try:
                yield
            finally:
                for task in tuple(tasks):
                    task.cancel()
                if tasks:
                    await asyncio.gather(*tuple(tasks), return_exceptions=True)

    app.router.lifespan_context = lifespan

    def store() -> WebAgentState:
        nonlocal state
        if state is None:
            state = WebAgentState(default_agent_state_path())
            state.recover_interrupted()
        return state

    def configured() -> bool:
        return (workspace / DEFAULT_AGENT_CONFIG).is_file() and DashboardService(
            workspace
        )._openrouter_configured()

    @app.middleware("http")
    async def assistant_boundary(request: Request, call_next: Any) -> Any:
        if request.url.path.startswith("/api/assistant"):
            origin = request.headers.get("origin")
            if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
                return Response("Cross-origin assistant requests are not allowed", status_code=403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return Response("Cross-site assistant requests are not allowed", status_code=403)
        return await call_next(request)

    def thread(identity: str) -> dict[str, Any]:
        try:
            result = store().thread(identity)
            job_id = result.get("job_id")
            if job_id:
                job = DashboardService(workspace).get_job(job_id)
                if job:
                    result["context_name"] = f"{job['title']} at {job['company']}"
            return result
        except LookupError as exc:
            raise HTTPException(404, "Conversation not found") from exc

    async def supervise(identity: str, operation: str, *, proposal: bool = False) -> None:
        process = None
        key = ("proposal:" if proposal else "turn:") + identity
        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "resume_builder.web_agent_worker",
                "--workspace",
                str(workspace),
                "--state",
                str(store().path),
                "--thread",
                identity,
                "--proposal" if proposal else "--run",
                operation,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            processes[key] = process
            await asyncio.wait_for(process.wait(), timeout=300)
            if proposal:
                pending = next(p for p in thread(identity)["proposals"] if p["id"] == operation)
                if pending["status"] == "applying":
                    store().finish_proposal(
                        identity,
                        operation,
                        "failed",
                        "The edit worker stopped. Check the current resume.",
                    )
            else:
                store().finish_turn(
                    identity, operation, "The response worker stopped before completing.", "failed"
                )
        except (OSError, TimeoutError):
            if process and process.returncode is None:
                process.kill()
                await process.wait()
            if proposal:
                store().finish_proposal(
                    identity,
                    operation,
                    "interrupted",
                    "The edit stopped. Check the current draft before retrying.",
                )
            else:
                store().finish_turn(
                    identity,
                    operation,
                    "The assistant timed out or could not start. Please try again.",
                    "failed",
                )
        finally:
            if process and process.returncode is None:
                process.kill()
                await process.wait()
            processes.pop(key, None)

    def launch(identity: str, operation: str, *, proposal: bool = False) -> None:
        task = asyncio.create_task(supervise(identity, operation, proposal=proposal))
        tasks.add(task)

        def completed(done: asyncio.Task[None]) -> None:
            tasks.discard(done)
            if not done.cancelled() and done.exception():
                logging.getLogger(__name__).error("Assistant worker supervision failed")

        task.add_done_callback(completed)

    @router.get("/status")
    async def status() -> dict[str, Any]:
        # Runs now start on this same-origin FastAPI service. The legacy runtime
        # bridge may be present for older clients, but it is not a health dependency.
        return {"configured": configured(), "online": True}

    @router.get("/threads")
    def threads() -> dict[str, Any]:
        return {"threads": store().list_threads()}

    @router.post("/threads", status_code=201)
    def create_thread(payload: dict[str, Any]) -> dict[str, Any]:
        selected = payload.get("resume_id")
        selected_job = payload.get("job_id")
        if selected is not None and selected_job is not None:
            raise HTTPException(400, "Choose either a resume or a job")
        if selected_job is not None:
            try:
                found = DashboardService(workspace).get_job(selected_job)
            except (ValueError, TypeError):
                found = None
            if found is None:
                raise HTTPException(400, "Choose an existing job")
            return store().create_thread(None, job_id=selected_job)
        try:
            if selected is not None:
                resume_path(workspace, selected)
            return store().create_thread(selected)
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, "Choose an existing directional resume") from exc

    @router.get("/threads/{identity}")
    def get_thread(identity: str) -> dict[str, Any]:
        return thread(identity)

    @router.post("/threads/{identity}/runs", status_code=202)
    async def start_turn(identity: str, payload: dict[str, Any]) -> dict[str, Any]:
        run_id = payload.get("run_id")
        prompt = payload.get("prompt")
        if (
            not isinstance(run_id, str)
            or not 1 <= len(run_id) <= 100
            or not isinstance(prompt, str)
            or not 1 <= len(prompt.strip()) <= 12000
        ):
            raise HTTPException(400, "Send one text message")
        thread(identity)
        if not configured():
            raise HTTPException(409, "Configure AI in Settings to start the assistant")
        try:
            started = store().begin_turn(identity, run_id, prompt)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        if started:
            launch(identity, run_id)
        return thread(identity)

    @router.post("/threads/{identity}/stop", status_code=204)
    async def stop(identity: str) -> None:
        current = thread(identity)
        for run in current["runs"]:
            store().finish_turn(identity, run["id"], "Response stopped.", "cancelled")
        process = processes.get("turn:" + identity)
        if process and process.returncode is None:
            process.terminate()
            await process.wait()

    @router.delete("/threads/{identity}", status_code=204)
    async def delete_thread(identity: str) -> None:
        await stop(identity)
        try:
            store().delete_thread(identity)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post("/threads/{identity}/proposals/{proposal_id}/{decision}")
    async def decide(identity: str, proposal_id: str, decision: str) -> dict[str, Any]:
        thread(identity)
        if decision not in {"accept", "decline"}:
            raise HTTPException(400, "Choose accept or decline")
        proposal = next(
            (item for item in thread(identity)["proposals"] if item["id"] == proposal_id), None
        )
        if proposal is None:
            raise HTTPException(404, "Proposed change not found")
        if (
            decision == "accept"
            and proposal["payload"].get("kind") not in {"resume_removal", "resume_restore"}
            and not configured()
        ):
            raise HTTPException(409, "Configure AI before applying a reviewed change")
        try:
            claimed = store().claim_proposal(identity, proposal_id)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        if claimed:
            if decision == "decline":
                store().finish_proposal(identity, proposal_id, "declined", "Resume unchanged.")
            else:
                launch(identity, proposal_id, proposal=True)
        return thread(identity)

    @router.post("/ag-ui")
    async def ag_ui(request: Request) -> StreamingResponse:
        secret = os.environ.get("RESUME_BUILDER_ASSISTANT_TOKEN", "")
        if not secret or not hmac.compare_digest(
            request.headers.get("x-assistant-token", ""), secret
        ):
            raise HTTPException(403, "Private agent endpoint")
        body = await request.body()
        if len(body) > 256_000:
            raise HTTPException(413, "Conversation request too large")
        try:
            payload = json.loads(body)
            identity, run_id = payload["threadId"], payload["runId"]
            prompt = payload["messages"][-1]["content"]
            role = payload["messages"][-1]["role"]
            if (
                not isinstance(identity, str)
                or not isinstance(run_id, str)
                or len(run_id) > 100
                or role != "user"
                or not isinstance(prompt, str)
                or not 1 <= len(prompt.strip()) <= 12000
            ):
                raise ValueError("Invalid user message")
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise HTTPException(400, "Send one text message") from exc
        thread(identity)
        if not configured():
            raise HTTPException(409, "Configure AI in Settings to start the assistant")
        try:
            started = store().begin_turn(identity, run_id, prompt)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        if started:
            launch(identity, run_id)

        async def events() -> Any:
            def event(kind: str, **data: Any) -> str:
                return "data: " + json.dumps({"type": kind, **data}) + "\n\n"

            yield event("RUN_STARTED", threadId=identity, runId=run_id)
            yield event("STEP_STARTED", stepName="Working with your private career workspace")
            while True:
                current = thread(identity)
                run = next(r for r in current["runs"] if r["id"] == run_id)
                if run["status"] != "running":
                    break
                yield ": keepalive\n\n"
                await asyncio.sleep(0.5)
            yield event("STEP_FINISHED", stepName="Working with your private career workspace")
            yield event("MESSAGES_SNAPSHOT", messages=current["messages"])
            yield event("RUN_FINISHED", threadId=identity, runId=run_id)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @router.api_route("/runtime/{path:path}", methods=["GET", "POST"])
    async def runtime_proxy(path: str, request: Request) -> Response:
        # No arbitrary destination, redirects, credentials or hop-by-hop headers.
        allowed = {"info", "agent/default/run", "agent/default/connect", "agent/default/stop"}
        if path not in allowed:
            raise HTTPException(404, "Assistant endpoint not found")
        body = await request.body()
        if len(body) > 256_000:
            raise HTTPException(413, "Conversation request too large")
        client = httpx.AsyncClient(timeout=httpx.Timeout(330, connect=3), trust_env=False)
        try:
            response = await client.send(
                client.build_request(
                    request.method,
                    "http://127.0.0.1:8768/" + path,
                    content=body,
                    headers={"Content-Type": "application/json"},
                ),
                stream=True,
            )
        except httpx.HTTPError as exc:
            await client.aclose()
            raise HTTPException(
                503, "Assistant temporarily unavailable. Please try again."
            ) from exc

        async def stream() -> Any:
            try:
                async for chunk in response.aiter_bytes():
                    yield chunk
            finally:
                await response.aclose()
                await client.aclose()

        return StreamingResponse(
            stream(),
            status_code=response.status_code,
            media_type=response.headers.get("content-type"),
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    app.include_router(router)
