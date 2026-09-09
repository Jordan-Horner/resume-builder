# Resume regression evaluations

Resume Builder keeps reproducible, fictional evaluation cases separate from the
private career vault. The implementation lives in
`resume_builder.quality_assurance.regression`; the established
`resume_builder.evaluations` import and `resume-builder eval` command remain
compatible.

An evaluation case pins its original source and expected material evidence. The
runner validates the sealed case before opening the generated resume, compiles
the current output, and compares selection, role coverage, and independent
review dimensions without making the evaluation source part of the vault.
