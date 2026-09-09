# Resume regression evaluations

Resume Builder keeps reproducible, fictional evaluation cases separate from the
private career vault. The implementation and `resume-builder eval` command live
in `resume_builder.quality_assurance.regression`.

An evaluation case pins its original source and expected material evidence. The
runner validates the sealed case before opening the generated resume, compiles
the current output, and compares selection, role coverage, and independent
review dimensions without making the evaluation source part of the vault.
