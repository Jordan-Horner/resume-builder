# Role database

The `directions/` directory is the canonical, Git-tracked role database.
Direction files describe researched positioning and evidence-selection guidance
for resume lanes such as technical support or incident management. They do not
contain candidate facts and are not created by hydration.

Profiles use the versioned contract in
`.agents/skills/build-resume/references/direction-contract.md`. Validate them
with `resume-builder direction validate` and audit a baseline with
`resume-builder direction audit <profile> <resume>`.

Start a new profile as `draft` and `provisional`. Unsourced assumptions remain
`needs-review`; later role research adds sources and raises maturity without
replacing the file or its stable concept IDs.

Concept `terms` are retrieval and discoverability signals, not sentences or
labels to copy into a resume. Use the optional `essential_terms` list only for a
small number of exact phrases that truly must appear. Direction audit scores
selected evidence independently, reports supporting vocabulary separately, and
emits advisory warnings for mechanical repetition without failing the build.

Use `.agents/skills/research-role/SKILL.md` to research an anchor role and its
peer market, then add or update the appropriate profile. The skill separates a
portable core from employer-, seniority-, and sector-specific overlays and
records current sources with stable `DIRSRC-NNN` IDs. Git history is the role
database's version history; do not create `v2` or `final` copies.
