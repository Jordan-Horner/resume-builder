import { lazy, Suspense, useCallback, useEffect, useRef, useState, type MouseEvent } from "react";
import { getOnboardingStatus } from "./api";
import type { OnboardingStatus } from "./types";
import { UpdateNotice, UpdateProvider } from "./updates";
import { AssistantProvider } from "./assistant/AssistantProvider";

const applicationsModule = () => import("./pages/ApplicationsPage");
const jobsModule = () => import("./pages/JobsPage");
const onboardingModule = () => import("./pages/OnboardingPage");
const resumesModule = () => import("./pages/ResumesPage");
const settingsModule = () => import("./pages/SettingsPage");

const ApplicationsPage = lazy(() => applicationsModule().then((module) => ({ default: module.ApplicationsPage })));
const JobsPage = lazy(() => jobsModule().then((module) => ({ default: module.JobsPage })));
const OnboardingPage = lazy(() => onboardingModule().then((module) => ({ default: module.OnboardingPage })));
const ResumesPage = lazy(() => resumesModule().then((module) => ({ default: module.ResumesPage })));
const SettingsPage = lazy(() => settingsModule().then((module) => ({ default: module.SettingsPage })));

type Route = "jobs" | "applications" | "resumes" | "settings";
const ROUTES: Route[] = ["jobs", "applications", "resumes", "settings"];
// The browser's module loader caches a dynamic import after the first call,
// so warming a route's chunk on hover/focus makes the later `lazy()` import
// (fired on click) resolve instantly instead of showing "Opening page…".
const ROUTE_PRELOADERS: Record<Route, () => void> = {
  jobs: () => void jobsModule(),
  applications: () => void applicationsModule(),
  resumes: () => void resumesModule(),
  settings: () => void settingsModule(),
};

function routeFromPath(): Route {
  const candidate = window.location.pathname.split("/")[1] as Route;
  if (window.location.pathname.split("/")[1] === "integrations") return "settings";
  return ROUTES.includes(candidate) ? candidate : "jobs";
}

export function App() {
  const [route, setRoute] = useState<Route>(routeFromPath);
  const [onboarding, setOnboarding] = useState<OnboardingStatus | null>(null);
  const [onboardingError, setOnboardingError] = useState("");
  const main = useRef<HTMLElement>(null);
  const initialRoute = useRef(true);

  useEffect(() => {
    getOnboardingStatus()
      .then(setOnboarding)
      .catch((reason: unknown) => setOnboardingError(
        reason instanceof Error ? reason.message : "Could not check workspace setup",
      ));
  }, []);

  useEffect(() => {
    if (window.location.pathname.split("/")[1] === "integrations") window.history.replaceState({}, "", "/settings/integrations");
  }, [route]);

  useEffect(() => {
    const handleNavigation = () => setRoute(routeFromPath());
    window.addEventListener("popstate", handleNavigation);
    return () => window.removeEventListener("popstate", handleNavigation);
  }, []);

  useEffect(() => {
    if (initialRoute.current) { initialRoute.current = false; return; }
    main.current?.focus();
  }, [route]);

  const navigate = useCallback((next: Route) => {
    if (next === "settings" && window.location.pathname.startsWith("/settings")) return;
    window.history.pushState({}, "", `/${next}`);
    setRoute(next);
  }, []);

  const followRoute = useCallback((event: MouseEvent<HTMLAnchorElement>, next: Route) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    navigate(next);
  }, [navigate]);

  if (onboardingError) {
    return <div className="startup-message"><strong>Could not open Resume Builder</strong><p>{onboardingError}</p></div>;
  }
  if (!onboarding) {
    return <div className="startup-message" role="status">Opening your private workspace…</div>;
  }
  if (onboarding.needs_onboarding) {
    return <Suspense fallback={<div className="startup-message" role="status">Opening setup…</div>}><OnboardingPage initial={onboarding} onComplete={() => setOnboarding({ ...onboarding, needs_onboarding: false })} /></Suspense>;
  }

  return (
    <UpdateProvider><AssistantProvider><div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to main content</a>
      <header className="topbar">
        <a className="brand" href="/jobs" onClick={(event) => followRoute(event, "jobs")} aria-label="Go to jobs">
          <span className="brand-mark" aria-hidden="true">RB</span>
          <span>Resume Builder</span>
        </a>
        <nav aria-label="Primary navigation">
          {ROUTES.map((item) => (
            <a
              key={item}
              className={route === item ? "nav-link active" : "nav-link"}
              href={`/${item}`}
              aria-current={route === item ? "page" : undefined}
              onMouseEnter={() => ROUTE_PRELOADERS[item]()}
              onFocus={() => ROUTE_PRELOADERS[item]()}
              onClick={(event) => followRoute(event, item)}
            >
              {item === "jobs" ? "Jobs" : item[0].toUpperCase() + item.slice(1)}
            </a>
          ))}
          <UpdateNotice />
        </nav>
      </header>
      <main id="main-content" ref={main} tabIndex={-1}>
        <Suspense fallback={<div className="startup-message" role="status">Opening page…</div>}>
          {route === "jobs" && <JobsPage />}
          {route === "applications" && <ApplicationsPage />}
          {route === "resumes" && <ResumesPage />}
          {route === "settings" && <SettingsPage />}
        </Suspense>
      </main>
    </div></AssistantProvider></UpdateProvider>
  );
}
