export type WorkMode = "remote" | "hybrid" | "onsite";
export type EmploymentType = "fulltime" | "parttime" | "contract" | "temporary";
export type ClearanceMode = "all" | "exclude" | "only";

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
  clearanceMode: ClearanceMode;
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

export interface JobScreenResult {
  status: "complete";
  cached: boolean;
  result: {
    job_id: string;
    fit: string;
    fit_label: string;
    screening_label: "Preference check" | "Quick screen";
    eligibility: string;
    eligibility_label: string;
    recommendation: string;
    recommendation_label: string;
    confidence: "high" | "medium" | "low";
    strengths: string[];
    gaps: string[];
    unknowns: string[];
    stretch_case: string | null;
    reasoning_summary: string;
    evidence_coverage: "good" | "partial" | "low";
    evidence_strategy?: "posting-wide" | "criterion-driven";
    criterion_evidence?: Array<{
      criterion_id: string;
      label: string;
      importance: "required" | "preferred";
      status: "demonstrated-candidate" | "supporting-candidate" | "no-candidate-evidence" | "not-resume-evaluable";
      fact_ids: string[];
    }>;
    criterion_assessments?: Array<{
      criterion_id: string;
      outcome: "supported" | "partially_supported" | "transferable" | "unknown" | "apparent_gap";
      confidence: "high" | "medium" | "low";
      fact_ids: string[];
      explanation: string;
      materially_affects_recommendation: boolean;
    }>;
    posting_coverage: "complete" | "partial";
    evidence_used: Array<{
      fact_id: string;
      title: string;
      category: "employment" | "projects" | "skills" | "education" | "certifications";
      strength: "demonstrated" | "supporting" | "credential";
    }>;
  };
}

export interface SalaryEstimateResult {
  status: "posted" | "estimated" | "unavailable";
  job_id: string;
  cached: boolean;
  posted_salary: Pick<Job, "salary_min" | "salary_max" | "salary_currency" | "salary_interval"> | null;
  estimate: {
    status: "estimated" | "unavailable";
    minimum: number | null;
    maximum: number | null;
    currency: string | null;
    period: "year" | "hour" | null;
    confidence: "low" | "medium" | "none";
    reasoning: string;
    company_basis: string;
    assumptions: string[];
    related_job_ids: string[];
  } | null;
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
  resume: ApplicationResume | null;
  resume_attribution: "tailored" | "directional" | "not_recorded";
}

export interface ApplicationResume {
  name: string;
  kind: "tailored" | "directional";
  path: string;
  sha256: string;
  available: boolean;
  preview_url: string | null;
  detail: string;
}

export interface Integration {
  id: string;
  name: string;
  description: string;
  status: "connected" | "configured" | "not_connected";
  detail: string;
}

export interface GmailSetupStep {
  number: number;
  total: number;
  title: string;
  instruction: string;
  link_label: string;
  link: string;
}

export interface GmailSetup {
  connected: boolean;
  privacy: string;
  steps: GmailSetupStep[];
}

export interface TelegramPairing {
  session_id: string;
  username: string;
  pairing_url: string;
  qr_url: string;
  status: "waiting" | "connected" | "failed";
  error: string;
  expires_at: string;
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
  | "activation"
  | "complete";

export interface SearchPreferences {
  status: "active" | "ready_to_activate" | "in_progress" | "skipped" | "not_configured";
  revision: string;
  titles: string[];
  country: string;
  work_modes: WorkMode[];
  onsite_locations: string[];
  remote_location_terms: string[];
  clearance_preference: "neutral" | "prefer" | "exclude";
  compensation: {
    skipped: boolean;
    minimum: number | null;
    target: number | null;
    currency: string | null;
    period: "hour" | "year" | null;
  };
}

export interface CareerResume {
  id: string;
  name: string;
  kind: "directional" | "tailored";
  status?: "active" | "retired";
  updated_at: string | null;
  detail: string;
  error: string | null;
  preview_url: string | null;
  preview_message: string | null;
}

export interface ResumeSection {
  id: "directional" | "tailored" | "retired";
  title: string;
  description: string;
  items: CareerResume[];
}

export interface ResumeLibrary { sections: ResumeSection[]; }

export interface ResumeRecommendation {
  status: "available" | "unavailable";
  recommended_resume: { id: string; name: string; kind: "directional" | "tailored" } | null;
  target: string | null;
  match: { label: "Strong match" | "Partial match" | "Weak match" | "Unknown match" } | null;
  message: string | null;
}

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
