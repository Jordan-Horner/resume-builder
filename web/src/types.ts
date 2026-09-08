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
  excludedWorkModes: WorkMode[];
  country: string;
  locations: string[];
  employmentTypes: EmploymentType[];
  excludedEmploymentTypes: EmploymentType[];
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
  description?: string;
  work_modes: string[];
  providers: string[];
  url: string | null;
  company_recognition?: {
    major_employer: boolean;
    top_workplace: boolean;
    sources: string[];
  } | null;
  quick_screen?: {
    status: "complete" | "skipped" | "failed";
    label: string;
    resume_name: string | null;
    generated_at: string | null;
  } | null;
  personalization?: {
    hot?: boolean;
    hot_reasons?: string[];
    hot_score: number;
  } | null;
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
    resume_match?: {
      resume_id: string;
      name: string;
      sha256: string;
      label: "Strong match" | "Partial match" | "Weak match" | "Unknown match";
      strongest_overlap: string[];
      primary_gap: string | null;
      alternative: {
        resume_id: string;
        name: string;
        label: "Strong match" | "Partial match" | "Weak match" | "Unknown match";
      } | null;
    } | null;
    posting_coverage: "complete" | "partial";
    evidence_used: Array<{
      fact_id: string;
      title: string;
      category: "employment" | "projects" | "skills" | "education" | "certifications";
      strength: "demonstrated" | "supporting" | "credential";
    }>;
  };
}

export interface JobScreenProgress {
  status: "idle" | "queued" | "running" | "failed";
  job_id: string;
  message?: string;
}

export type JobScreenState = JobScreenResult | JobScreenProgress;

export type JobFeedbackAction = "interested" | "not_interested";
export type JobFeedbackReason = "company" | "compensation" | "customer_facing" | "day_to_day" | "location" | "on_call" | "phone_support" | "role" | "seniority" | "travel" | "work_mode";
export type JobHideReason = "closed" | "duplicate" | "not_relevant";
export interface HiddenJobResult {
  job_id: string;
  reason: JobHideReason;
  personalization_updated: boolean;
}
export interface JobFeedback {
  job_id: string;
  latest: { action: "interested" | "not_interested" | "applied"; reasons: JobFeedbackReason[]; created_at: string } | null;
  personalization: {
    hot_label: "Hot job" | "Recommended" | "Promising" | "Learning your preferences" | "Low priority";
    fit_score: number;
    interest_score: number;
    company_score: number;
    fit_label: "Strong" | "Neutral" | "Low";
    interest_label: "High" | "Neutral" | "Low";
    company_label: "Positive" | "Neutral" | "Low";
    confidence: "high" | "medium" | "low" | "unknown";
    reasons: string[];
    hot: boolean;
    hot_reasons: string[];
  };
  dismissal_follow_up?: {
    ask_why: boolean;
    prompt: string | null;
    recommendation_reasons: string[];
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
  reapplication: ReapplicationOpportunity | null;
}

export interface ReapplicationOpportunity {
  application_id: string;
  prior_job_id: string;
  job_id: string;
  kind: "reopened" | "possible_repost";
  company: string;
  role: string;
  url: string;
  detected_at: string;
  reason: string;
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
  settings?: {
    enabled: boolean;
    max_records_per_refresh: number;
  };
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
  preferred_job_attributes: string[];
  avoided_job_attributes: string[];
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
