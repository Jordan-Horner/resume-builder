export type WorkMode = "remote" | "hybrid" | "onsite";
export type EmploymentType = "fulltime" | "parttime" | "contract" | "temporary";

export interface JobFilters {
  view?: ViewFilters;
  search: string;
  workMode: WorkMode | "";
  dateDays: 0 | 1 | 3 | 7 | 14 | 30;
  employmentType: EmploymentType | "";
}

export interface ViewFilters {
  roles: string[];
  workModes: WorkMode[];
  country: string;
  locations: string[];
  employmentTypes: EmploymentType[];
  minimumPay: number | null;
  currency: string;
  period: "year" | "hour";
  includeUnknownPay: boolean;
  includeUnknownMode: boolean;
  includeUnmatchedLocation: boolean;
}

export interface Job {
  id: string;
  title: string;
  company: string;
  location: string;
  employment_type: string | null;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string | null;
  salary_interval: string | null;
  posted_at: string | null;
  first_seen_at: string | null;
  description: string;
  work_modes: string[];
  providers: string[];
  url: string | null;
}

export interface ApplicationEvent {
  id: string;
  status: string;
  effective_on: string;
  stage: string | null;
  note: string | null;
}

export interface Application {
  id: string;
  company: string;
  role: string;
  job_id: string | null;
  application_url: string | null;
  applied_on: string;
  current_status: string;
  events: ApplicationEvent[];
}

export interface Integration {
  id: string;
  name: string;
  description: string;
  status: "connected" | "configured" | "not_connected";
  detail: string;
  setup_command: string;
}

export interface OnboardingStatus {
  needs_onboarding: boolean;
  step: OnboardingStep;
  progress: number;
  resume_count: number;
  resume_names: string[];
  openrouter_configured: boolean;
  setup: OnboardingSetup | null;
}

export type OnboardingStep =
  | "resume"
  | "ai_choice"
  | "roles"
  | "eligibility"
  | "location"
  | "compensation"
  | "review"
  | "complete";

export type RoleIntent = "search" | "explore" | "dont_seed";

export interface RoleProposal {
  role_id: string;
  title: string;
  group: "current_recent" | "related" | "earlier";
  intent: RoleIntent;
  reason: string;
}

export interface OnboardingSetup {
  session_id: string;
  status: string;
  step: OnboardingStep;
  roles: RoleProposal[];
  eligibility: {
    intended_country: string;
    authorized_to_work: boolean | null;
    requires_sponsorship: boolean | null;
    held_clearances: string[];
    holds_clearance_or_public_trust?: boolean | null;
    willing_to_obtain_clearance: boolean | null;
  } | null;
  location: {
    accepted_work_modes: WorkMode[];
    accepted_onsite_locations: string[];
    remote_location_terms: string[] | null;
  } | null;
  compensation: {
    skipped: boolean;
    minimum: number | null;
    target: number | null;
    currency: string | null;
    period: "hour" | "year" | null;
  } | null;
}
