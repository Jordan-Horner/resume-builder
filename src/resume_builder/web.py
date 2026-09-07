"""Local web server for the Resume Builder dashboard."""

import argparse
from pathlib import Path
from typing import Any

from .agent_contracts import ModelProviderError, ModelProviderTimeoutError
from .web_service import DashboardService, ScreeningInputError
from .workspace_state import discover_workspace


def create_app(workspace: Path, *, static_dir: Path | None = None) -> Any:
    try:
        from fastapi import (
            BackgroundTasks,
            FastAPI,
            File,
            HTTPException,
            Query,
            Request,
            Response,
            UploadFile,
        )
        from fastapi.responses import FileResponse, RedirectResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:
        raise RuntimeError(
            'web dependencies are missing; install with pip install -e ".[web]"'
        ) from exc

    service = DashboardService(workspace)
    from .web_integrations import GMAIL_CLIENT_MAX_BYTES, PortalIntegrationService

    integration_service = PortalIntegrationService(workspace)
    resolved_static = static_dir.expanduser().resolve() if static_dir else None
    from .updates import UpdateChecker

    updates = UpdateChecker()
    from .web_job_sources import source_status, start_scan, toggle_source
    from .web_schedule import save_schedule, schedule_status
    from .web_system import system_status

    app = FastAPI(title="Resume Builder", docs_url="/api/docs", redoc_url=None)
    from .web_agent import install_assistant

    install_assistant(app, workspace)

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

    async def import_career_material(file: UploadFile) -> dict[str, Any]:
        try:
            content = await file.read(10 * 1024 * 1024 + 1)
            return service.import_resume(file.filename or "", content)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            await file.close()

    @app.post("/api/onboarding/resume", status_code=201)
    async def upload_resume(file: UploadFile = File(...)) -> dict[str, Any]:  # noqa: B008
        return await import_career_material(file)

    @app.post("/api/career-material/resumes", status_code=201)
    async def upload_career_material(
        file: UploadFile = File(...),  # noqa: B008
    ) -> dict[str, Any]:
        return await import_career_material(file)

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

    @app.post("/api/job-search/roles/preview")
    def preview_role_titles(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return service.preview_role_titles(payload)
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

    @app.get("/api/resumes")
    def resumes() -> dict[str, Any]:
        try:
            return service.career_resumes()
        except ValueError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/resume-preview")
    def resume_preview(resume_id: str = Query(min_length=1, max_length=500)) -> FileResponse:
        try:
            document = service.career_resume_preview(resume_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(
            document["path"],
            media_type=document["media_type"],
            filename=document["filename"],
            content_disposition_type="inline",
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": (
                    "sandbox; default-src 'none'; style-src 'unsafe-inline'; "
                    "img-src data:; font-src data:"
                ),
            },
        )

    @app.post("/api/resumes/restore")
    def restore_resume(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            resume_id = payload.get("resume_id")
            if not isinstance(resume_id, str):
                raise ValueError("Choose a retired résumé")
            return service.restore_career_resume(resume_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/applications/{application_id}/resume-preview")
    def application_resume_preview(application_id: str) -> FileResponse:
        try:
            document = service.application_resume_preview(application_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(
            document["path"],
            media_type=document["media_type"],
            filename=document["filename"],
            content_disposition_type="inline",
            headers={
                "Cache-Control": "private, max-age=31536000, immutable",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": (
                    "sandbox; default-src 'none'; style-src 'unsafe-inline'; "
                    "img-src data:; font-src data:"
                ),
            },
        )

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
        hot_only: bool = Query(default=False),
        queue: str = Query(default="all", max_length=20),
        limit: int = Query(default=100, ge=1, le=200),
    ) -> dict[str, Any]:
        try:
            items = service.list_jobs(
                search=search,
                work_mode=work_mode,
                date_days=date_days,
                employment_type=employment_type,
                view_filters=view_filters,
                hot_only=hot_only,
                queue=queue,
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

    @app.post("/api/jobs/{job_id}/estimate-salary")
    def estimate_job_salary(job_id: str, refresh: bool = False) -> dict[str, Any]:
        try:
            return service.estimate_job_salary(job_id, refresh=refresh)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ModelProviderTimeoutError as exc:
            raise HTTPException(
                status_code=504,
                detail="Job screening timed out. Please try again.",
            ) from exc
        except ModelProviderError as exc:
            raise HTTPException(
                status_code=502, detail="Salary estimation failed. Please try again."
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(
                status_code=500, detail="Could not read or save the salary estimate."
            ) from exc

    @app.get("/api/jobs/{job_id}/salary-estimate")
    def saved_job_salary(job_id: str) -> Any:
        try:
            result = service.saved_job_salary(job_id)
            return result if result is not None else Response(status_code=204)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (OSError, ValueError) as exc:
            raise HTTPException(
                status_code=500, detail="Could not read the saved salary estimate."
            ) from exc

    @app.get("/api/jobs/{job_id}/resume-recommendation")
    def job_resume_recommendation(job_id: str) -> dict[str, Any]:
        try:
            return service.job_resume_recommendation(job_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/jobs/{job_id}/screen")
    def saved_job_screen(job_id: str) -> Any:
        try:
            result = service.saved_job_screen(job_id)
            return result if result is not None else Response(status_code=204)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/jobs/{job_id}/screen")
    def screen_job(job_id: str, refresh: bool = False) -> dict[str, Any]:
        try:
            return service.screen_job(job_id, refresh=refresh)
        except ScreeningInputError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except UnicodeError as exc:
            raise HTTPException(
                status_code=500,
                detail=(
                    "Job screening could not read one of its inputs. "
                    "Refresh your jobs and try again."
                ),
            ) from exc
        except ModelProviderError as exc:
            raise HTTPException(
                status_code=502, detail="Job screening failed. Please try again."
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/jobs/{job_id}/feedback")
    def job_feedback(job_id: str) -> dict[str, Any]:
        try:
            return service.job_feedback(job_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/jobs/{job_id}/opened-posting", status_code=204)
    def record_job_open(job_id: str) -> None:
        try:
            service.record_job_open(job_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/jobs/{job_id}/feedback")
    def record_job_feedback(
        job_id: str, payload: dict[str, Any], background_tasks: BackgroundTasks
    ) -> dict[str, Any]:
        try:
            result = service.record_job_feedback(
                job_id,
                payload.get("action"),
                payload.get("reasons", []),
            )
            background_tasks.add_task(service.replenish_recommendations)
            return result
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/jobs/{job_id}/not-interested")
    def mark_not_interested(job_id: str, background_tasks: BackgroundTasks) -> dict[str, Any]:
        try:
            result = service.mark_not_interested(job_id)
            background_tasks.add_task(service.replenish_recommendations)
            return result
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/jobs/{job_id}/applied", status_code=201)
    def mark_applied(job_id: str, background_tasks: BackgroundTasks) -> dict[str, Any]:
        try:
            result = service.mark_applied(job_id)
            background_tasks.add_task(service.replenish_recommendations)
            return result
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

    @app.put("/api/integrations/openrouter")
    def configure_openrouter(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return service.configure_openrouter(payload.get("api_key"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put("/api/integrations/bright-data")
    def configure_bright_data(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return service.configure_bright_data(
                payload.get("api_token"),
                payload.get("enabled"),
                payload.get("max_records_per_refresh"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/integrations/bright-data/enrich")
    def enrich_bright_data() -> dict[str, Any]:
        try:
            return service.enrich_bright_data()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/integrations/gmail/setup")
    def gmail_setup() -> dict[str, Any]:
        return integration_service.gmail_setup()

    @app.post("/api/integrations/gmail/authorize")
    async def authorize_gmail(
        request: Request,
        file: UploadFile = File(...),  # noqa: B008
    ) -> dict[str, str]:
        try:
            content = await file.read(GMAIL_CLIENT_MAX_BYTES + 1)
            return integration_service.begin_gmail_oauth(
                file.filename or "",
                content,
                redirect_uri=str(request.base_url).rstrip("/"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            await file.close()

    @app.post("/api/integrations/telegram/pairing", status_code=202)
    def start_telegram_pairing(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return integration_service.start_telegram_pairing(payload.get("token"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/integrations/telegram/pairing/{session_id}")
    def telegram_pairing_status(session_id: str) -> dict[str, Any]:
        try:
            return integration_service.telegram_pairing_status(session_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/integrations/telegram/pairing/{session_id}/qr")
    def telegram_pairing_qr(session_id: str) -> Response:
        try:
            content = integration_service.telegram_pairing_qr(session_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return Response(
            content=content,
            media_type="image/svg+xml",
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.get("/", include_in_schema=False)
    def portal_root(request: Request, state: str = "", code: str = "", error: str = "") -> Any:
        if error:
            return RedirectResponse("/settings/integrations?gmail=cancelled", status_code=303)
        if state and code:
            try:
                integration_service.complete_gmail_oauth(state, str(request.url))
            except ValueError:
                return RedirectResponse("/settings/integrations?gmail=error", status_code=303)
            return RedirectResponse("/settings/integrations?gmail=connected", status_code=303)
        if resolved_static and (resolved_static / "index.html").is_file():
            return FileResponse(resolved_static / "index.html")
        raise HTTPException(status_code=404, detail="Portal frontend is unavailable")

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
