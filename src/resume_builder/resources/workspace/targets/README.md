# Target Postings

Store one Git-tracked Markdown record for each real job posting used to tailor or
review a resume. A target preserves the posting snapshot, its source and hash,
focused required/preferred criteria, and exact search groups. It is not a role
profile and never introduces candidate facts.

Use `directions/` for reusable role-family knowledge. Use `targets/` only when a
real posting URL, pasted description, or supplied file exists. Generated match
reports belong under `build/matches/` and are disposable.

Run a resume-only audit with:

```bash
resume-builder match validate
resume-builder match targets/<posting>.md resumes/baselines/<direction>.md
```

For a tailored resume, preserve the baseline and compare both:

```bash
resume-builder match \
  targets/<posting>.md \
  resumes/tailored/<company>-<role>.md \
  --baseline resumes/baselines/<direction>.md
```

The command reports exact term locations and baseline deltas. It does not
produce an ATS score or decide whether the resume semantically satisfies the
posting.
