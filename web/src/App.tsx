import { useCallback, useEffect, useState } from "react";
import { getOnboardingStatus } from "./api";
import { ApplicationsPage } from "./pages/ApplicationsPage";
import { JobsPage } from "./pages/JobsPage";
import { OnboardingPage } from "./pages/OnboardingPage";
import { SettingsPage } from "./pages/SettingsPage";
import type { OnboardingStatus } from "./types";

type Route = "jobs" | "applications" | "settings";
const ROUTES: Route[] = ["jobs", "applications", "settings"];

function routeFromPath(): Route {
  const candidate = window.location.pathname.split("/")[1] as Route;
  if (window.location.pathname.split("/")[1] === "integrations") return "settings";
  return ROUTES.includes(candidate) ? candidate : "jobs";
}

export function App() {
  const [route, setRoute] = useState<Route>(routeFromPath);
  const [onboarding, setOnboarding] = useState<OnboardingStatus | null>(null);
  const [onboardingError, setOnboardingError] = useState("");

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

  const navigate = useCallback((next: Route) => {
    if (next === "settings" && window.location.pathname.startsWith("/settings")) return;
    window.history.pushState({}, "", `/${next}`);
    setRoute(next);
  }, []);

  if (onboardingError) {
    return <div className="startup-message"><strong>Could not open Resume Builder</strong><p>{onboardingError}</p></div>;
  }
  if (!onboarding) {
    return <div className="startup-message" role="status">Opening your private workspace…</div>;
  }
  if (onboarding.needs_onboarding) {
    return <OnboardingPage initial={onboarding} onComplete={() => setOnboarding({ ...onboarding, needs_onboarding: false })} />;
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <button className="brand" onClick={() => navigate("jobs")} aria-label="Go to jobs">
          <span className="brand-mark" aria-hidden="true">RB</span>
          <span>Resume Builder</span>
        </button>
        <nav aria-label="Primary navigation">
          {ROUTES.map((item) => (
            <button
              key={item}
              className={route === item ? "nav-link active" : "nav-link"}
              onClick={() => navigate(item)}
            >
              {item === "jobs" ? "Jobs" : item[0].toUpperCase() + item.slice(1)}
            </button>
          ))}
        </nav>
      </header>
      <main>
        {route === "jobs" && <JobsPage />}
        {route === "applications" && <ApplicationsPage />}
        {route === "settings" && <SettingsPage />}
      </main>
    </div>
  );
}
