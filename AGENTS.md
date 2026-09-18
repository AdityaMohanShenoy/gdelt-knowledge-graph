# Agent Instructions

These instructions apply to every agent working in this repository.

## Start of every task

1. Read this file completely.
2. Inspect `.agents/` recursively for relevant skills.
3. Read every relevant `SKILL.md` before taking task actions.
4. Inspect the repository state, existing documentation, tests, and manifests.
5. Make or confirm a focused plan before implementation.

Use local skills to improve the work when they apply. Do not load unrelated skills. If a task changes GitHub commits, branches, or pull requests, read `.agents/gh/SKILL.md` and the references it routes to.

## Scope and plan

- Implement only the approved plan and the requested feature.
- Do not add stubs, placeholders, TODOs, speculative abstractions, or future-facing code.
- If implementation reveals a requirement outside the plan, stop and ask for the plan to be updated before continuing.
- Preserve unrelated working-tree changes and untracked files.

## Documentation

- After every code, configuration, data, or workflow change, update the most appropriate existing Markdown documentation in the same change.
- If no appropriate documentation file exists, stop and ask the user to approve creating a new Markdown file. After approval, create a useful document and write its content before continuing.
- Never create an empty documentation placeholder.
- Keep documentation consistent with the actual implementation. Do not document planned behavior as available behavior.

## Implementation quality

- Implement the complete requested behavior; do not leave partial paths or fake success responses.
- Do not add new source-code comments, block comments, inline comments, or docstrings. Put explanations in Markdown documentation instead.
- Existing unrelated comments may remain; do not remove them as collateral cleanup.
- Follow the repository’s existing language, formatting, typing, and dependency conventions.

## Tests and checks

- Every code behavior change must include unit tests and the relevant integration or end-to-end tests.
- Documentation-only and agent-policy changes must have appropriate validation, including syntax, links, metadata, and whitespace checks.
- Before a pull request, run every applicable test suite declared by the repository, including Python tests, TypeScript tests, and end-to-end tests, plus linting and type checks.
- A suite that is missing, empty, or cannot run is not a passing suite. Report the blocker and do not claim that all checks passed.
- Do not weaken, delete, or bypass tests to make a change pass.

## Commits and working context

- Every commit must address one coherent change.
- Use Conventional Commits with one of these types: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, or `chore`.
- Use the format `type(scope): imperative description` when a scope is useful.
- When the working context exceeds 8 changed files, or contains unrelated concerns, stop and show the user a brief summary. Suggest splitting the work into focused commits.
- Read `.agents/gh/SKILL.md` before preparing or creating commits.

## Pull requests

- Pull requests must be draft pull requests.
- Do not create a pull request until documentation, acceptance criteria, and all applicable checks are complete and passing.
- Read `.agents/gh/SKILL.md` for branch checks, canonical titles, remote pull-request handling, approval boundaries, and required pull-request content.
