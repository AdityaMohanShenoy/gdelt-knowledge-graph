---
name: gh
description: Prepare Conventional Commits and draft GitHub pull requests with branch, test, documentation, and remote-PR checks.
metadata:
  short-description: Prepare clean commits and draft pull requests
---

# GitHub Workflow

Use this skill for Git branches, Conventional Commits, GitHub pull requests, and related release workflow. Read the repository root `AGENTS.md` first. Read [commit-conventions.md](references/commit-conventions.md) when preparing a commit and [pr-workflow.md](references/pr-workflow.md) when preparing a pull request.

## Before changing Git state

- Inspect the working tree, current branch, upstream, and changed-file count.
- The default pull-request base is `development` unless the user specifies another base.
- If the current branch is a base branch, stop before committing and ask the user for a feature branch.
- Check the approved plan, documentation updates, and required tests before preparing a commit.
- If the working tree exceeds 8 changed files or mixes unrelated contexts, stop and suggest focused commits.

## Commits

- Use one atomic commit per coherent change.
- Use a lowercase Conventional Commit type: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, or `chore`.
- Prepare the proposed commit message and a short change summary for the user.
- Ask for user confirmation before staging or creating the commit.
- After confirmation, create only the approved atomic commit. Do not amend or rewrite existing commits unless the user explicitly chooses that workflow.

## Pull requests

- Before opening a new pull request, check every remote pull request associated with the current branch, including closed and merged records.
- Use `gh` for GitHub operations. Do not create a duplicate pull request.
- If a remote pull request exists, stop and ask the user to choose either:
  - Update/rebase the existing pull request on the configured base branch.
  - Create a stacked pull request from a new branch whose base is the existing pull-request branch.
- Run all applicable test suites, linting, and type checks only after the final changes are present. Do not open a pull request while any required check is failing or unavailable.
- Before pushing or opening a pull request, show the user a brief summary containing the branch, base, title, changes, acceptance criteria, tests, and documentation updates. Ask for confirmation before remote mutations.
- After confirmation, push the branch and create a draft pull request.

## Pull-request title and body

Use a lowercase Conventional Commit prefix in every title:

`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `perf:`, or `chore:`

Titles must be concise, specific, imperative, and free of trailing punctuation. The body must include a summary of changes or fixes, acceptance criteria with tested/met status, all checks run with their results, and documentation updated.
