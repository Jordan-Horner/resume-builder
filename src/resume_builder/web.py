"""Local web server for the Resume Builder dashboard."""

import argparse
from pathlib import Path
from typing import Any

from .web_service import DashboardService
from .workspace_state import discover_workspace


def create_app(workspace: Path, *, static_dir: Path | None = None) -> Any:
    try:
        from fastapi import FastAPI, File, HTTPException, Query, UploadFile
        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:
        raise RuntimeError(
            'web dependencies are missing; install with pip install -e ".[web]"'
        ) from exc

    service = DashboardService(workspace)
    from .updates import UpdateChecker

    updates = UpdateChecker()
    from .web_job_sources import source_status, start_scan, toggle_source
    from .web_schedule import save_schedule, schedule_status
    from .web_system import system_status

    app = FastAPI(title="Resume Builder", docs_url="/api/docs", redoc_url=None)

    @app.get("/api/system/version")
    def system_version() -> dict[str, Any]:
        return updates.status()

    @app.get("/api/system/status")
    def runtime_status() -> dict[str, Any]:
        return system_status(workspace)

    @app.get("/api/onboarding")
    def onboarding() -> dict[str, Any]:
        try:
            return service.onboarding_status()
        except ValueError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/onboarding/resume", status_code=201)
    async def upload_resume(file: UploadFile = File(...)) -> dict[str, Any]:  # noqa: B008
        try:
            content = await file.read(10 * 1024 * 1024 + 1)
            return service.import_resume(file.filename or "", content)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            await file.close()

    @app.post("/api/onboarding/skip", status_code=204)
    def skip_onboarding() -> None:
        service.skip_onboarding()

    @app.post("/api/onboarding/start")
    def start_onboarding(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return service.start_preference_setup(
                use_ai=bool(payload.get("use_ai")),
                api_key=str(payload.get("api_key") or ""),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/onboarding/answer")
    def answer_onboarding(payload: dict[str, Any]) -> dict[str, Any]:
        answer = payload.get("answer")
        if not isinstance(answer, dict):
            raise HTTPException(status_code=400, detail="answer must be an object")
        try:
            return service.answer_preference_step(str(payload.get("step") or ""), answer)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/onboarding/back")
    def back_onboarding() -> dict[str, Any]:
        try:
            return service.previous_preference_step()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/job-search/activate")
    def activate_job_search() -> dict[str, Any]:
        try:
            return service.activate_job_search()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/job-search/preferences")
    def job_search_preferences() -> dict[str, Any]:
        try:
            return service.job_search_preferences()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put("/api/job-search/preferences")
    def update_job_search_preferences(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return service.update_job_search_preferences(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/job-filter-defaults")
    def job_filter_defaults() -> dict[str, Any]:
        try:
            return service.job_filter_defaults()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/jobs")
    def jobs(
        search: str = Query(default="", max_length=200),
        work_mode: str = Query(default="", max_length=20),
        date_days: int = Query(default=0),
        employment_type: str = Query(default="", max_length=20),
        view_filters: str = Query(default="", max_length=12000),
        limit: int = Query(default=100, ge=1, le=200),
    ) -> dict[str, Any]:
        try:
            items = service.list_jobs(
                search=search,
                work_mode=work_mode,
                date_days=date_days,
                employment_type=employment_type,
                view_filters=view_filters,
            )
            reviewable = service.list_jobs()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "jobs": items[:limit],
            "count": len(items),
            "reviewable_count": len(reviewable),
        }

    @app.get("/api/blocked-companies")
    def blocked_companies() -> dict[str, Any]:
        try:
            return {"companies": service.blocked_companies()}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put("/api/blocked-companies")
    def block_company(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            company, blocked = payload.get("company"), payload.get("blocked")
            if not isinstance(company, str) or not isinstance(blocked, bool):
                raise ValueError("company must be text and blocked must be a boolean")
            return {"companies": service.set_company_blocked(company, blocked)}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str) -> dict[str, Any]:
        item = service.get_job(job_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return item

    @app.post("/api/jobs/{job_id}/not-interested", status_code=204)
    def mark_not_interested(job_id: str) -> None:
        try:
            service.mark_not_interested(job_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/jobs/{job_id}/applied", status_code=201)
    def mark_applied(job_id: str) -> dict[str, Any]:
        try:
            return service.mark_applied(job_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/applications")
    def applications() -> dict[str, Any]:
        items = service.list_applications()
        return {"applications": items, "count": len(items)}

    @app.get("/api/job-sources")
    def job_sources() -> dict[str, Any]:
        try:
            return source_status(workspace)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put("/api/job-sources/{provider}")
    def set_job_source(provider: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            enabled = payload.get("enabled")
            if not isinstance(enabled, bool):
                raise ValueError("enabled must be a boolean")
            return toggle_source(workspace, provider, enabled)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/job-sources/scan")
    def scan_job_sources() -> dict[str, Any]:
        try:
            return start_scan(workspace)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/scrape-schedule")
    def scrape_schedule() -> dict[str, Any]:
        try:
            return schedule_status(workspace)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put("/api/scrape-schedule")
    def update_scrape_schedule(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return save_schedule(workspace, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/integrations")
    def integrations() -> dict[str, Any]:
        return {"integrations": service.list_integrations()}

    resolved_static = static_dir.expanduser().resolve() if static_dir else None
    if resolved_static and (resolved_static / "index.html").is_file():
        assets = resolved_static / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def frontend(path: str) -> FileResponse:
            candidate = (resolved_static / path).resolve()
            if path and candidate.is_file() and candidate.is_relative_to(resolved_static):
                return FileResponse(candidate)
            return FileResponse(resolved_static / "index.html")

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local Resume Builder dashboard")
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--static-dir", type=Path, default=Path("web/dist"))
    args = parser.parse_args()
    workspace = args.workspace.expanduser().resolve() if args.workspace else discover_workspace()
    if workspace is None:
        parser.error("no Resume Builder workspace could be discovered")
    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit(
            'web dependencies are missing; install with pip install -e ".[web]"'
        ) from exc
    uvicorn.run(create_app(workspace, static_dir=args.static_dir), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
