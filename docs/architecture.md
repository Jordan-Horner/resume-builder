# Architecture

![Resume Builder architecture](assets/architecture.png)

Resume Builder separates durable evidence from generated presentation. The
boundary is deliberate: changing a sentence should not change the underlying
career history, and passing a structural check should not be mistaken for
editorial approval.

## Layers

1. **Sources** preserve imported resumes and notes as untrusted evidence.
2. **Canonical facts** store one versioned claim per Markdown file with source
   provenance, employment scope, and confirmation status.
3. **Directions and targets** describe the role being pursued. They guide
   selection but can never become candidate evidence.
4. **Synthesis plans** make story selection, omissions, reviewer risks, and
   evidence composition inspectable before prose is written.
5. **Resume Markdown** is the only editable presentation source. Every factual
   block cites canonical fact IDs.
6. **Preview** compiles the current Markdown, checks structure, evidence,
   numeric claims, authorship, and stale inputs, then publishes editable HTML.
7. **Editing** returns directly to preview after each user-requested change.
8. **Optional review** provides selection, cold-language, matching, or hiring
   analysis only when the user explicitly requests it.
9. **Minting** treats the explicit mint request as approval of the current
   preview and adds page-budget, overflow, network, JavaScript, and
   text-extraction checks.

## Trust boundaries

| Input | What it may influence | What it may not establish |
|---|---|---|
| Imported resume or career note | Candidate fact proposals | Canonical truth without review |
| Role research | Direction and terminology | Candidate experience |
| Job posting | Selection and match criteria | Candidate experience |
| Language model | Drafting and judgment | Unsupported facts or authority |
| Deterministic compiler | Traceability and structural integrity | Persuasiveness or semantic truth |
| Selection reviewer | Story choice and complete hiring argument | New facts or resume prose |
| Career-professional review | Language quality and hiring read | New factual evidence or story deletion |

## Dependency shape

The package is organized around functional workflows rather than a web-service
layering model. `atomic`, `layout`, `rendering`, and `validation` provide shared
boundaries. Higher-level modules orchestrate source import, synthesis,
compilation, verification, feedback, review, matching, preview, and minting.

Dependency-neutral modules now separate canonical Markdown parsing, feedback
resolution, review schema enforcement, and synthesis models from the workflows
that write artifacts. Feedback acceptance pins the user-approved preview, while
compilation depends only on feedback resolution; neither relationship points
back toward its caller. The package import graph is therefore acyclic.

`review_records.py` historically owned package construction, decision
finalization, wording-only repair, record loading, freshness, and approval
enforcement. Those responsibilities now live behind a small compatibility
facade:

- `review_blocks.py` inventories narrative prose and deterministic advisories;
- `review_packages.py` builds cold-read and evidence-appendix artifacts;
- `review_decisions.py` finalizes reviewer-owned decisions;
- `review_repairs.py` applies the guarded wording-only repair pass;
- `review_schema.py` strictly loads compatible record versions;
- `review_approval.py` enforces freshness for explicitly requested critiques.

Compatibility facades keep every pre-split public symbol importable from its
original module and list it in `__all__`. A regression test pins that surface so
future extractions cannot silently break callers while moving implementation.

The same dependency direction applies to the other orchestration domains.
Job matching keeps untrusted posting validation and Markdown rendering in
separate boundary modules while its public facade owns retrieval orchestration
and CLI compatibility.
Workspace state and remote-privacy inspection are similarly isolated from the
mutating initialization and connection workflow.
Project reporting uses typed artifact-status records and shared freshness
helpers while preserving its stable JSON-facing report contract.
`resume_parser.py` is independent of build orchestration; feedback recording,
acceptance, and resolution are separate; synthesis models, loading, and auditing
are separate; synthesis schema primitives and direction-derived inputs are kept
outside the version-aware plan assembler; direction parsing and diagnostics are
separate; and report policy is pure workflow logic. The architecture check
rejects package cycles, forbidden reverse imports, and facade growth beyond
their reviewed budgets.

## Release invariants

- Canonical facts are never edited outside a validated change plan.
- A `needs-review` fact cannot appear in visible resume prose.
- High-authority verbs must be supported by the action evidence.
- A changed resume or evidence source makes the published preview stale until
  `preview` recompiles it.
- Preview and mint do not require an optional critique record.
- An explicit mint invocation approves only the exact current preview.
- PDF minting cannot bypass page-budget or extraction failures.
