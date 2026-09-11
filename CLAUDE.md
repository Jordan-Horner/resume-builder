@AGENTS.md

# Claude Code compatibility

`AGENTS.md` is the canonical repository instruction file. Do not duplicate or
reinterpret its workflow here.

Claude Code discovers project skills through `.claude/skills/`. Those files are
small compatibility entry points; every substantive workflow remains canonical
under `.agents/skills/`. When an adapter applies, read its referenced canonical
`SKILL.md` completely and resolve supporting files relative to that canonical
skill directory.
