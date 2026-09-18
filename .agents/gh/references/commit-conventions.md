# Commit Conventions

Use one commit for one coherent change. Split the work when the implementation contains separate user-visible outcomes, unrelated contexts, or more than 8 changed files.

## Format

```text
type(scope): imperative description
```

Allowed types:

- `feat`: new user-visible behavior.
- `fix`: correction of incorrect behavior.
- `docs`: documentation-only changes.
- `test`: test-only changes.
- `refactor`: behavior-preserving structure changes.
- `perf`: performance improvements.
- `chore`: maintenance, tooling, or dependency changes.

Keep the subject specific and concise. Use a scope when it makes the affected subsystem clearer. Do not add a trailing period. Breaking changes must be called out explicitly in the commit body and pull-request body.

Before creating a commit, report the proposed message, changed-file summary, tests, documentation, and acceptance criteria to the user and wait for confirmation.
