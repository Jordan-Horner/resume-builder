from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
HYDRATE_SKILL = ROOT / ".agents" / "skills" / "hydrate-vault"
BUILD_SKILL = ROOT / ".agents" / "skills" / "build-resume"
CRITIQUE_SKILL = ROOT / ".agents" / "skills" / "critique-resume"
RESEARCH_SKILL = ROOT / ".agents" / "skills" / "research-role"
MATCH_SKILL = ROOT / ".agents" / "skills" / "match-job"
SCREEN_SKILL = ROOT / ".agents" / "skills" / "screen-job"


def test_agents_file_is_canonical_and_names_safe_commands() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    normalized_agents = " ".join(agents.split())

    assert "CODEX.md" not in agents
    assert "resume-builder hydrate" in agents
    assert "resume-builder plan apply" in agents
    assert "resume-builder review language-package" in agents
    assert "resume-builder review language-finalize" in agents
    assert ".agents/skills/build-resume/SKILL.md" in agents
    assert "Never ask the user to repeat information" in normalized_agents
    assert "do not create a separately maintained" in normalized_agents
    assert "versioned synthesis plan" in normalized_agents
    assert "do not mechanically convert one fact into one bullet" in normalized_agents
    assert "finish the new draft before opening the original" in normalized_agents
    assert "cold-reader context test" in normalized_agents
    assert "reviewer cannot access internal company context" in normalized_agents
    assert "--prune-excluded" not in agents


def test_agents_file_routes_empty_and_hydrated_startup_states() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    normalized_agents = " ".join(agents.split())

    assert "No source material or canonical facts" in agents
    assert "exact folder path" in agents
    assert "pasted resume text" in agents
    assert "guided career-history interview" in normalized_agents
    assert "Canonical facts but no generated resumes" in agents
    assert "Do not ask for source resumes again" in normalized_agents
    assert "Never search the user's home directory" in normalized_agents


def test_agents_and_skills_resolve_the_private_workspace_before_file_access() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    normalized_agents = " ".join(agents.split())

    assert "resume-builder workspace show" in agents
    assert "Shell tools, file readers, patch tools, and Git commands do not" in normalized_agents
    assert "Never create candidate files" in normalized_agents
    for skill in (
        HYDRATE_SKILL,
        BUILD_SKILL,
        CRITIQUE_SKILL,
        RESEARCH_SKILL,
        MATCH_SKILL,
        SCREEN_SKILL,
    ):
        text = (skill / "SKILL.md").read_text(encoding="utf-8")
        assert "resume-builder workspace show" in text
        assert "engine" in text


def test_skill_metadata_and_interface_match() -> None:
    skill_text = (HYDRATE_SKILL / "SKILL.md").read_text(encoding="utf-8")
    _, frontmatter, _ = skill_text.split("---", 2)
    metadata = yaml.safe_load(frontmatter)
    interface = yaml.safe_load(
        (HYDRATE_SKILL / "agents" / "openai.yaml").read_text(encoding="utf-8")
    )

    assert metadata["name"] == "hydrate-vault"
    assert "Do not use" in metadata["description"]
    assert interface["interface"]["display_name"] == "Hydrate Vault"
    assert "$hydrate-vault" in interface["interface"]["default_prompt"]


def test_skill_uses_preview_and_plan_boundaries() -> None:
    skill = (HYDRATE_SKILL / "SKILL.md").read_text(encoding="utf-8")
    normalized_skill = " ".join(skill.split())

    assert "plan validate" in skill
    assert "plan preview" in skill
    assert "plan apply" in skill
    assert "Never write canonical facts" in skill
    assert "--prune-excluded" not in skill
    assert "exact folder path" in skill
    assert "paste resume text" in normalized_skill
    assert "guided career-history interview" in normalized_skill
    assert "Do not search the home directory" in normalized_skill
    assert "distinguish extraction completeness from semantic completeness" in normalized_skill
    assert "intentionally generalized for privacy" in normalized_skill
    assert "high word-overlap score" in normalized_skill
    assert "mechanism from one source with an outcome from another" in normalized_skill
    assert "generated resume as a source claim" in normalized_skill
    assert "schema-v2.md" in skill
    assert "scope: organization" in skill
    assert "exact current canonical fact" in normalized_skill
    assert "compare it with the exact replacement the user approved" in normalized_skill
    assert "do not repeat the fact or ask another verification question" in normalized_skill


def test_build_resume_skill_routes_and_preserves_work() -> None:
    skill_text = (BUILD_SKILL / "SKILL.md").read_text(encoding="utf-8")
    normalized_skill = " ".join(skill_text.split())
    _, frontmatter, _ = skill_text.split("---", 2)
    metadata = yaml.safe_load(frontmatter)
    interface = yaml.safe_load((BUILD_SKILL / "agents" / "openai.yaml").read_text(encoding="utf-8"))

    assert metadata["name"] == "build-resume"
    assert "directional resume" in metadata["description"]
    assert "hydrate-vault" in metadata["description"]
    assert interface["interface"]["display_name"] == "Build Resume"
    assert "$build-resume" in interface["interface"]["default_prompt"]
    assert "Never ask" in skill_text
    assert "Git history" in skill_text
    assert "resumes/baselines/<direction>.md" in skill_text
    assert "resumes/tailored/<company>-<role>.md" in skill_text
    assert "do not create a separately" in skill_text
    assert "resume-builder preview" in skill_text
    assert "resume-builder mint" in skill_text
    assert "resume-builder review route" in skill_text
    assert "resume-builder review language-package" in skill_text
    assert "resume-builder review language-finalize" in skill_text
    assert "Compilation never creates a PDF" in skill_text
    assert "Never hand-edit generated HTML" in normalized_skill
    assert "no generated resumes" in skill_text
    assert "do not route that user back to source intake" in skill_text
    assert "direction validate" in skill_text
    assert "direction audit" in skill_text
    assert "unsourced model knowledge" in skill_text
    assert "do not read hydrated source snapshots" in skill_text
    assert "vault/sources/normalized/" in skill_text
    assert "generic AI-purple styling" in skill_text
    assert "resume-quality-contract.md" in skill_text
    assert "evidence opportunity" in normalized_skill
    assert "do not consolidate roles" in skill_text
    assert "Do not guess" in skill_text
    assert "present a supported project" in normalized_skill
    assert "This is a preservation check, not a second editorial critique" in normalized_skill
    assert "perform the resume quality review" not in skill_text
    assert "Persist it through hydration first" in normalized_skill
    assert "synthesis contract" in normalized_skill
    assert "resumes/plans/<resume-slug>.yaml" in skill_text
    assert "story clusters" in normalized_skill
    assert "distinct bullet jobs" in normalized_skill
    assert "do not map one fact mechanically to one bullet" in normalized_skill
    assert "textual difference" in normalized_skill
    assert "Core Competencies as optional" in normalized_skill
    assert "resume-template-contract.md" in skill_text
    assert "technical-classic" in skill_text
    assert "must never be relabeled as Core Competencies" in normalized_skill
    assert "retrieval signals, not preferred wording" in normalized_skill
    assert "`demonstrated`" in skill_text
    assert "`transferable`" in skill_text
    assert "reviewer risk map" in normalized_skill
    assert "required target criteria" in normalized_skill
    assert "audience-calibrated specificity pass" in normalized_skill
    assert "not a prohibited-word list" in normalized_skill
    assert "automatic preference for broader wording" in normalized_skill
    assert "cold-reader context test" in normalized_skill
    assert "internal names as provenance, not explanation" in normalized_skill
    assert "project, system, team, workflow, or process name" in normalized_skill
    assert "preview → edit → preview" in normalized_skill
    assert "exclusive-current-stage" in normalized_skill
    assert "supersedes_prior_handoffs" in normalized_skill
    assert "complete final handoff" in normalized_skill
    assert "without adding earlier-stage confirmations" in normalized_skill
    assert "When the user adds content during preview" in skill_text
    assert "no more than two materially useful enrichment questions" in normalized_skill
    assert "changed-block language review" in normalized_skill
    assert "competitive-but-improvable" in normalized_skill
    assert "feedback-memory contract" in normalized_skill
    assert "resume-builder feedback resolve" in normalized_skill
    assert "resume-builder feedback accept" in normalized_skill
    assert "latest open-session revisions" in normalized_skill
    assert "approved standalone language record" in normalized_skill
    assert "structured claim boundary" in normalized_skill
    assert "required versus optional stories" in normalized_skill
    assert "`claim_focus`" in skill_text
    assert "`core_fact_ids`" in skill_text
    assert "complete fact pool as a checklist" in normalized_skill
    assert "core fact is required proof" in normalized_skill
    assert "run a subtraction pass" in normalized_skill
    assert "separate inventories of actions and technical surfaces" in normalized_skill
    assert "raw technology-surface inventory" in normalized_skill
    assert "one functional scope phrase" in normalized_skill
    assert "Do not make one bullet perform both" in skill_text
    assert "raw comma-separated inventory" in normalized_skill
    assert "evidence containers rather than story boundaries" in normalized_skill
    assert "strategic-relationship test" in normalized_skill
    assert "explicit role arc" in normalized_skill
    assert "rather than a bullet quota" in normalized_skill
    assert "perform a redistribution check" in normalized_skill
    assert "silently narrow the role's career story" in normalized_skill
    assert "cold-read" in normalized_skill
    assert "contribution-first verb test" in normalized_skill
    assert "omit the story rather than reaching for a stronger synonym" in normalized_skill
    assert "Never cite a `needs-review` fact" in skill_text
    assert "action-verb lists as brainstorming aids" in normalized_skill
    assert "Classify the change by meaning, not edit size" in normalized_skill
    assert "freeze the resume" in normalized_skill
    assert "no more than two materially useful enrichment questions" in normalized_skill
    assert "concise `Saved` receipt" in normalized_skill
    assert "show only the exact `Current fact`, exact `Proposed fact`" in normalized_skill
    assert "do not add a recommendation or change-log section" in normalized_skill


def test_feedback_contract_separates_wording_edits_from_fact_changes() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    normalized_agents = " ".join(agents.split())
    contract = (BUILD_SKILL / "references" / "feedback-memory-contract.md").read_text(
        encoding="utf-8"
    )
    normalized_contract = " ".join(contract.split())

    for text in (normalized_agents, normalized_contract):
        assert "Classify" in text and "meaning" in text
        assert "word count" in text
        assert "wording-only" in text
        assert "authorship" in text
        assert "exact current canonical fact" in text
        assert "exact proposed" in text
        assert "no more than two" in text
        assert "matches" in text and "approved" in text
        assert "Keep the resume" in text or "keep the resume" in text
        assert "kept, omitted, reframed, or replaced" in text
        assert "resume remains unchanged" in text

    assert "Do not add `My read`" in contract
    assert "**Current fact**" in contract
    assert "**Proposed fact**" in contract
    assert "**Saved**" in contract
    assert "another verification question" in contract
    assert "**Is this accurate?**" not in contract
    assert "**Current bullet**" in contract
    assert "**Proposed bullet**" in contract
    assert "**Update this bullet and refresh the preview?**" in contract
    assert "Other affected resumes will remain unchanged" in contract
    assert "### **<Company> — <Role>**" in contract
    assert (
        "exactly from the affected bullet's visible resume placement heading" in normalized_contract
    )
    assert "never infer, normalize, promote, or otherwise rename the role" in normalized_contract
    assert "### **<Company> — <Role>**" in agents
    assert "exactly from that bullet's visible resume placement heading" in normalized_agents


def test_feedback_contract_keeps_uncertain_sentence_drafting_conversational() -> None:
    agents = " ".join((ROOT / "AGENTS.md").read_text(encoding="utf-8").split())
    skill = " ".join((BUILD_SKILL / "SKILL.md").read_text(encoding="utf-8").split())
    contract = " ".join(
        (BUILD_SKILL / "references" / "feedback-memory-contract.md")
        .read_text(encoding="utf-8")
        .split()
    )

    for text in (agents, skill, contract):
        assert "three to five materially different alternatives" in text
        assert "read-only" in text
        assert "Do not record" in text or "do not record" in text
        assert "meaning" in text
    assert "Exploring" in contract
    assert "Needs factual clarification" in contract
    assert "Ready to apply" in contract
    assert "not as a fourth workflow state" in contract
    assert "hardcoded list" in contract
    assert "without another confirmation" in contract


def test_critique_skill_owns_mandatory_editorial_approval_and_is_non_mutating() -> None:
    skill_text = (CRITIQUE_SKILL / "SKILL.md").read_text(encoding="utf-8")
    normalized_skill = " ".join(skill_text.split())
    _, frontmatter, _ = skill_text.split("---", 2)
    metadata = yaml.safe_load(frontmatter)
    interface = yaml.safe_load(
        (CRITIQUE_SKILL / "agents" / "openai.yaml").read_text(encoding="utf-8")
    )
    contract = (CRITIQUE_SKILL / "references" / "critique-contract.md").read_text(encoding="utf-8")
    normalized_contract = " ".join(contract.split())

    assert metadata["name"] == "critique-resume"
    assert "competitive-but-improvable" in metadata["description"]
    assert "standalone independent natural-language review" in metadata["description"]
    assert "Do not" in metadata["description"]
    assert interface["interface"]["display_name"] == "Critique Resume"
    assert "$critique-resume" in interface["interface"]["default_prompt"]
    assert "career-strategist" in interface["interface"]["default_prompt"]
    assert "hybrid route" in interface["interface"]["default_prompt"]
    assert "independent language decisions" in interface["interface"]["default_prompt"]
    assert "Do not edit the resume unless the user asks" in skill_text
    assert "Do not infer a role assignment" in skill_text
    assert "Ready to mint" in contract
    assert "no more than five targeted questions" in skill_text
    assert "resume-builder review question-plan" in normalized_skill
    assert "stable `gap_key`" in normalized_skill
    assert "build with the evidence we have" in normalized_skill
    assert "never continue an open-ended interview" in normalized_skill
    assert all(route in contract for route in ("`rebuild`", "`hydrate`", "`direction`", "`mint`"))
    assert "one primary route" in contract
    assert "material content or direction change" in skill_text
    assert "registered and applied through `hydrate-vault`" in skill_text
    assert "source manifest" in normalized_skill
    assert "registered source snapshots" in normalized_skill
    assert "Ask the user only when neither layer answers" in normalized_skill
    assert "Do not convert compiler or direction warnings directly" in normalized_skill
    assert "approximate" in contract
    assert "unresolved choices would change" in contract
    assert "truthful project or employer-level presentation" in contract
    assert "summary and labels sound specific" in normalized_skill
    assert "repetition warning is not a deterministic failure" in normalized_skill
    assert "seasoned career strategist" in normalized_skill
    assert "career-strategist lens" in normalized_skill
    assert "employer lens" in normalized_skill
    assert "strongest reason to interview" in normalized_skill
    assert "most likely objection" in normalized_skill
    assert "compelling" in contract
    assert "credible but not yet differentiated" in contract
    assert "not a prediction of an employer's decision" in normalized_contract
    assert "direct recommendation" in contract
    assert "main tradeoff" in contract
    assert "soft skills are demonstrated" in normalized_contract
    assert "Do not praise every section" in skill_text
    assert "six-second top-third test" in normalized_skill
    assert "reviewer risk map" in normalized_skill
    assert "partially resolved" in contract
    assert "audience-calibrated specificity check" in normalized_skill
    assert "adds no decision-relevant meaning" in normalized_contract
    assert "not a preference for broad or nontechnical language" in normalized_contract
    assert "resume-builder review package" in normalized_skill
    assert "resume-builder review apply-repairs" in normalized_skill
    assert "feedback_review" in skill_text
    assert "complies" in skill_text
    assert "Never expose" in skill_text
    assert "wording-only" in normalized_contract
    assert "Version 1 decisions remain finalizable" in contract
    assert "every narrative block" in normalized_skill
    assert "Never let the builder assign its own" in normalized_skill
    assert "Narrative-block language gate" in contract
    assert "Enforce a one-point budget" in contract
    assert "normally use no more than two supporting details" in normalized_contract
    assert "three or more parallel mechanisms" in normalized_contract
    assert "not a banned-word list" in normalized_contract
    assert "Adjacent-heading test" in contract
    assert "Opening-removal test" in contract
    assert "Neighbor test" in contract
    assert "Cold-reader-in-context test" in contract
    assert "unstated premise" in normalized_contract
    assert "relationship the reader must invent" in normalized_contract
    assert "Role-arc completeness" in contract
    assert "dominant-claim and strategic-relationship" in normalized_contract
    assert "factual compatibility alone does not justify" in normalized_skill
    assert "not a bullet count" in normalized_skill
    assert "There is no universal ideal count" in contract
    assert "overload revision made prose cleaner" in normalized_skill
    assert "scope, authority, chronology, contrast, uncertainty" in normalized_contract
    assert "prompt for judgment, not a deterministic failure" in normalized_contract
    assert "before consulting synthesis notes or builder rationale" in normalized_contract
    assert '"version": 4' in contract
    assert "independent-cold-review" in normalized_skill
    assert "only the `.cold.json` file" in normalized_skill
    assert '"evidence_integrity"' in contract
    assert '"language_review"' in contract
    assert "single-context-review" in normalized_contract
    assert "an `approved` decision must also include a concise note" in normalized_contract
    assert "resume-builder review validate" in contract
    assert "never bypasses a `revise` decision" in normalized_contract
    assert "direct-relationship and opening-rhythm checks" in normalized_contract
    assert "Neither check is a banned-word list" in normalized_contract


def test_resume_drafting_does_not_copy_planning_shorthand_into_prose() -> None:
    skill = (BUILD_SKILL / "SKILL.md").read_text(encoding="utf-8")
    synthesis = (BUILD_SKILL / "references" / "synthesis-contract.md").read_text(encoding="utf-8")
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    normalized_skill = " ".join(skill.split())
    normalized_synthesis = " ".join(synthesis.split())
    normalized_agents = " ".join(agents.split())

    assert "natural-voice test" in normalized_skill
    assert "constructed modifiers hide how a technology relates" in normalized_skill
    assert "run of identical opening verbs" in normalized_skill
    assert "Never copy it mechanically into the resume" in normalized_synthesis
    assert "compressed modifiers or noun stacks" in normalized_synthesis
    assert "inspect their rhythm across the complete role" in normalized_synthesis
    assert "natural-voice test before review" in normalized_agents
    assert "unsupported synonym rotation" in normalized_agents


def test_critique_answers_route_through_hydration_before_final_use() -> None:
    hydrate = (HYDRATE_SKILL / "SKILL.md").read_text(encoding="utf-8")
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    normalized_agents = " ".join(agents.split())
    normalized_hydrate = " ".join(hydrate.split())

    assert "build/intake/<date>-<topic>.md" in hydrate
    assert "normal hydrate command" in normalized_hydrate
    assert "do not leave reusable career facts only in conversation history" in normalized_hydrate
    assert "answer is absent from" in normalized_hydrate
    assert "do not ask again" in normalized_hydrate
    assert "never copy the surrounding conversation" in normalized_hydrate
    assert "question-resolve" in normalized_hydrate
    assert "registered career-note source" in normalized_agents
    assert "search canonical facts first" in normalized_agents
    assert "prompt/build → language review → hybrid fit route" in normalized_agents
    assert "Saying `Mint` is explicit approval" in normalized_agents
    assert "competitive-but-improvable" in normalized_agents
    assert "empty approval cannot silently dismiss" in normalized_agents
    assert (
        "If a draft is weak, the agent checks your saved career evidence and imported sources"
        in " ".join(readme.split())
    )


def test_build_resume_references_define_evidence_and_regression_contracts() -> None:
    generation = (BUILD_SKILL / "references" / "generation-contract.md").read_text(encoding="utf-8")
    regression = (BUILD_SKILL / "references" / "regression-review.md").read_text(encoding="utf-8")
    direction = (BUILD_SKILL / "references" / "direction-contract.md").read_text(encoding="utf-8")
    synthesis = (BUILD_SKILL / "references" / "synthesis-contract.md").read_text(encoding="utf-8")
    normalized_synthesis = " ".join(synthesis.split())

    assert "<!-- evidence:" in generation
    assert "The vault is the master career record" in generation
    assert "original resume" in generation
    assert "resumes/baselines/" in generation
    assert "resumes/tailored/" in generation
    assert "Added" in regression
    assert "Removed" in regression
    assert "Rewritten" in regression
    assert "Obtain confirmation" in regression
    assert "Fresh-baseline source comparison" in regression
    assert "Strengthened" in regression
    assert "Vault gap" in regression
    assert "evidence used from other source resumes" in regression
    assert "wording-similarity test" in regression
    assert "story clusters" in synthesis
    assert "Bullet jobs" in synthesis
    assert "one primary job" in synthesis
    assert "not by automatically turning every fact" in synthesis
    assert "not a candidate-fact source" in normalized_synthesis
    assert "compiler rejects" in normalized_synthesis
    assert "Version 1" in synthesis
    assert "Version 2" in synthesis
    assert "Version 3" in synthesis
    assert "Version 4" in synthesis
    assert "Version 5" in synthesis
    assert "Version 6" in synthesis
    assert "Version 8" in synthesis
    assert "Version 9" in synthesis
    assert "Supporting stories may be omitted" in normalized_synthesis
    assert "summary_fact_ids" in synthesis
    assert "complete evidence set" in normalized_synthesis
    assert "demonstrated" in synthesis
    assert "transferable" in synthesis
    assert "unsupported" in synthesis
    assert "reviewer-risk map" in synthesis
    assert "target_mode" in synthesis
    assert "concept_fit" in synthesis
    assert "presentation" in synthesis
    assert "claim_focus" in synthesis
    assert "core_fact_ids" in synthesis
    assert "available evidence, not a checklist" in normalized_synthesis
    assert "unused optional fact ids" in normalized_synthesis.lower()
    assert "role_arcs" in synthesis
    assert "structured action/object/scope/outcome boundary" in normalized_synthesis
    assert "resolved page budget" in normalized_synthesis
    assert "required_story_ids" in synthesis
    assert "role_anchor_story_ids" in synthesis
    assert "role_selling_story_ids" in synthesis
    assert "not minimum or maximum bullet counts" in normalized_synthesis
    assert "Follow subtraction with redistribution" in synthesis
    assert "not a visible summary of every detail inside the fact" in normalized_synthesis
    assert "Run a subtraction test" in synthesis
    assert "honest lead is only `used`" in normalized_synthesis
    assert "never authorize stronger authorship or authority" in normalized_synthesis
    assert "must not cite `needs-review` facts" in generation
    assert "maturity: provisional" in direction
    assert "needs-review" in direction
    assert "resume-builder direction audit" in direction
    assert "legacy `score` field aliases `evidence_score`" in " ".join(direction.split())
    assert "experience_evidence_score" in direction
    assert "editorial_status: not-reviewed" in direction


def test_build_resume_rendering_contract_uses_vault_evidence() -> None:
    rendering = (BUILD_SKILL / "references" / "rendering-contract.md").read_text(encoding="utf-8")

    assert "resume-builder render" in rendering
    assert "data-evidence" in rendering
    assert "canonical fact IDs" in rendering
    assert "single column" in rendering
    assert "resume-builder compile" in rendering
    assert "#087f8c" in rendering
    assert "#245f8f" in rendering
    assert "user_handoff" in rendering
    assert "rendered_markdown" in rendering
    assert "bare link" in rendering


def test_agent_contract_requires_preview_handoff_to_be_presented() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    skill = (BUILD_SKILL / "SKILL.md").read_text(encoding="utf-8")

    assert "structured" in agents and "`user_handoff`" in agents
    assert "`rendered_markdown`" in agents
    assert "bare link" in agents
    assert "structured" in skill and "`user_handoff.rendered_markdown`" in skill
    assert "immediately" in skill


def test_match_job_skill_preserves_job_specific_boundaries() -> None:
    skill_text = (MATCH_SKILL / "SKILL.md").read_text(encoding="utf-8")
    contract = (MATCH_SKILL / "references" / "match-contract.md").read_text(encoding="utf-8")
    grading = (MATCH_SKILL / "references" / "grading-contract.md").read_text(encoding="utf-8")
    interface = yaml.safe_load((MATCH_SKILL / "agents" / "openai.yaml").read_text())
    normalized_skill = " ".join(skill_text.split())

    assert "real job posting" in skill_text
    assert "Do not use for a general role-family resume" in skill_text
    assert "resume-builder match" in skill_text
    assert "met" in skill_text
    assert "partial" in skill_text
    assert "not_met" in skill_text
    assert "undecidable" in skill_text
    assert "Never report a universal ATS percentage" in skill_text
    assert "Never inject every posting keyword" in skill_text
    assert "Never mint a PDF" in skill_text
    assert "resume-builder match classify" in skill_text
    assert "--classification-case" in skill_text
    assert "rebuild" in normalized_skill
    assert "hydrate" in normalized_skill
    assert "direction" in normalized_skill
    assert "accept-gap" in normalized_skill
    assert "body_sha256" in contract
    assert "baseline and tailored" in contract
    assert "resume-only match" in contract
    assert "mandatory-role-defining" in grading
    assert "Resume polish" in grading
    assert "Weak match" in grading
    assert interface["interface"]["display_name"] == "Match Job"
    assert "$match-job" in interface["interface"]["default_prompt"]


def test_screen_job_skill_is_compact_read_only_triage() -> None:
    skill_text = (SCREEN_SKILL / "SKILL.md").read_text(encoding="utf-8")
    contract = (SCREEN_SKILL / "references" / "screen-contract.md").read_text(encoding="utf-8")
    interface = yaml.safe_load((SCREEN_SKILL / "agents" / "openai.yaml").read_text())
    normalized_skill = " ".join(skill_text.split())
    normalized_contract = " ".join(contract.split())

    assert "screen this job" in skill_text
    assert "read-only" in normalized_skill
    assert "do not create one merely to screen" in normalized_skill
    assert "scripts/fetch_posting.py" in skill_text
    assert "public job-board API" in normalized_skill
    assert "resume-builder match classify" in normalized_skill
    assert "Use its label unchanged" in skill_text
    assert "use browser rendering only" in normalized_skill
    assert "one-page" in normalized_skill
    assert "Match" in contract
    assert "Closest resume" in contract
    assert "ATS visibility" in contract
    assert "Undisclosed Client" in contract
    assert "never title the screen with the intermediary" in normalized_contract
    assert "integer number of years in business" in normalized_contract
    assert "never show only `founded in <year>`" in normalized_contract
    assert "Remote, Hybrid, or On-site" in contract
    assert "Full-time, Part-time, or Contract" in contract
    assert "Annual:" in contract
    assert "Hourly:" in contract
    assert "Annualized equivalent:" in contract
    assert "| **Benefits**" in contract
    assert "**Compensation:** Not specified" in contract
    assert "job-specific benefits are absent, show `Not specified`" in normalized_contract
    assert contract.index("| **Pay**") < contract.index("| **Benefits**")
    assert "show hourly pay only when the posting states an hourly rate" in normalized_skill
    assert "Do not derive or display an hourly rate from annual compensation" in contract
    assert "general consultant FAQ does not establish benefits" in normalized_contract
    assert "roughly 350 words" in normalized_contract
    assert "Is this a stretch?" in contract
    assert "Do you have a matching resume?" in normalized_skill
    assert "**Match: <fixed match label>**" in contract
    assert "**Closest resume:**" in contract
    assert "**Strongest overlap:**" in contract
    assert "**Primary gap:**" in contract
    assert "**ATS visibility:**" in contract
    assert contract.index("**Match: <fixed match label>**") < contract.index("| **Company**")
    assert "**Recommendation:" not in contract
    assert "Low priority" not in contract
    assert "one specific next action" in normalized_contract
    assert "Mandatory and role-defining" in contract
    assert "Mandatory but substitutable" in contract
    assert "Lifestyle constraint" in contract
    assert "eligibility risk separately from transferable overlap" in normalized_skill
    assert "do not let it satisfy the eligibility gate" in normalized_contract
    assert "capability clusters" in normalized_contract
    assert "Do not count missing keywords" in normalized_contract
    assert "fixed number of gaps" in normalized_contract
    assert "assume that tools in the same category are equivalent" in normalized_contract
    assert "percentages, points, or a universal score" in normalized_contract
    assert "Required primary-platform tenure" in contract
    assert "accepted equivalent capability" in contract
    assert "candidate evidence is incomplete" in contract
    assert "every role-defining minimum" in normalized_contract.lower()
    assert "completed evidence search" in normalized_contract
    assert "treat that requirement as unsupported" in normalized_contract
    for label in ("Strong", "Partial", "Weak", "Unknown"):
        assert f"**{label} match**" in contract
    assert "**Bad match**" not in contract
    assert interface["interface"]["display_name"] == "Screen Job"
    assert "$screen-job" in interface["interface"]["default_prompt"]

    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    normalized_agents = " ".join(agents.split())
    assert ".agents/skills/screen-job/SKILL.md" in agents
    assert "Do not route a lightweight job screen here" in normalized_agents
    assert "Screen this job" in readme


def test_resume_quality_contract_teaches_principles_not_copywriting() -> None:
    quality = (BUILD_SKILL / "references" / "resume-quality-contract.md").read_text(
        encoding="utf-8"
    )
    normalized_quality = " ".join(quality.split())

    assert "transferable resume advice" in normalized_quality
    assert "not preferred sentences" in normalized_quality
    assert "Direction coverage is necessary but not sufficient" in quality
    assert "Evidence hierarchy" in quality
    assert "Keep separate roles" in quality
    assert "Each bullet must advance the case" in normalized_quality
    assert "restate a duty or quality" in normalized_quality
    assert "information budget" in quality
    assert "role-arc completeness" in quality
    assert "not a universal minimum or maximum" in normalized_quality
    assert "arbitrary bullet count" in normalized_quality
    assert "Git history" in quality
    assert "evidence-opportunity list" in quality
    assert "Rebuild from the expanded vault" in quality
    assert "stock title-plus-years formula" in normalized_quality
    assert "Competencies are optional" in quality
    assert "Calibrate specificity to the section, evidence, and intended audience" in quality
    assert "preserves decision-relevant meaning" in normalized_quality
    assert "do not ban terms" in normalized_quality
    assert "automatically prefer broader wording" in normalized_quality
    assert "Specificity and context independence" in quality
    assert "cold-reader context test" in normalized_quality
    assert "reviewer sees only the resume" in normalized_quality
    assert "must not carry the sentence's meaning" in normalized_quality
    assert "problem, function, audience, scale, or value" in normalized_quality
    assert "unstated-premise test" in normalized_quality
    assert "actor, action, object" in normalized_quality
    assert "relationship the reader must invent" in normalized_quality
    assert "not a new fact-specific editorial rule" in normalized_quality
    assert "concrete-object test" in normalized_quality
    assert "grammatically complete yet remain uninformative" in normalized_quality
    assert "system, deliverable, operation, or change" in normalized_quality
    assert "not by exact-word matching" in normalized_quality
    assert "Natural voice test" in quality
    assert "Apply a one-point budget" in quality
    assert "normally carry no more than two supporting details" in normalized_quality
    assert "three or more parallel items" in normalized_quality
    assert "main function is to inventory" in normalized_quality
    assert "judge the sentence by its function" in normalized_quality
    assert "Would a capable manager plausibly use this language" in normalized_quality
    assert "Do not enforce a banned-word list" in normalized_quality
    assert "direct relationships over constructed modifiers" in normalized_quality
    assert "framework-enabled" in quality
    assert "Read opening verbs across each role" in normalized_quality
    assert "Do not rotate synonyms merely for variety" in normalized_quality
    assert "visible resume context" in normalized_quality
    assert "adjacent heading" in normalized_quality
    assert "opening words loses no supported scope" in normalized_quality
    assert "scope, authority, chronology, contrast, uncertainty" in normalized_quality
    assert "does not ban a phrase" in normalized_quality


def test_build_resume_markdown_contract_is_strict_and_compilable() -> None:
    contract = (BUILD_SKILL / "references" / "markdown-contract.md").read_text(encoding="utf-8")

    assert "resume-builder compile" in contract
    assert "<!-- evidence:" in contract
    assert "Professional Summary" in contract
    assert "Work Experience" in contract
    assert "fails rather than dropping" in contract


def test_research_role_skill_maintains_sourced_role_database() -> None:
    skill_text = (RESEARCH_SKILL / "SKILL.md").read_text(encoding="utf-8")
    normalized_skill = " ".join(skill_text.split())
    _, frontmatter, _ = skill_text.split("---", 2)
    metadata = yaml.safe_load(frontmatter)
    interface = yaml.safe_load(
        (RESEARCH_SKILL / "agents" / "openai.yaml").read_text(encoding="utf-8")
    )
    contract = (RESEARCH_SKILL / "references" / "research-contract.md").read_text(encoding="utf-8")
    normalized_contract = " ".join(contract.split())

    assert metadata["name"] == "research-role"
    assert "anchor job posting" in metadata["description"]
    assert "Do not use role research as evidence" in metadata["description"]
    assert interface["interface"]["display_name"] == "Research Role"
    assert "$research-role" in interface["interface"]["default_prompt"]
    assert "directions/" in skill_text
    assert "representative peer set" in normalized_skill
    assert "portable core" in normalized_skill
    assert "untrusted data" in normalized_skill
    assert "resume-builder direction validate" in skill_text
    assert "Do not build or mint" in normalized_skill
    assert "Never infer direct people management" in normalized_skill
    assert "anchor plus portable core" in normalized_contract
    assert "official employer career pages" in normalized_contract
    assert "10\N{EN DASH}20" in contract
    assert "Operational and process ownership" in contract
    assert "People leadership and team enablement" in contract
    assert "candidate evidence gap" in normalized_contract
    assert "Never convert role-market research into a candidate claim" in normalized_contract


def test_agents_routes_role_research_without_blurring_candidate_evidence() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    directions = (ROOT / "directions" / "README.md").read_text(encoding="utf-8")
    normalized_agents = " ".join(agents.split())

    assert ".agents/skills/research-role/SKILL.md" in agents
    assert "canonical, Git-tracked role database" in normalized_agents
    assert "anchor posting" in normalized_agents
    assert "representative peer set" in normalized_agents
    assert "never turn market research directly into a resume claim" in normalized_agents
    assert "canonical, Git-tracked role database" in directions
    normalized_directions = " ".join(directions.split())
    assert "Git history is the role database's version history" in normalized_directions
