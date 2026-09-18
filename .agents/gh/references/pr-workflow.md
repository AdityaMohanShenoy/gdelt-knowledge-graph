# Pull Request Workflow

The default base branch is `development`. A user-provided base branch takes precedence.

## Required pull-request body

```markdown
## Summary

Describe the completed change or fix.

## Acceptance criteria

- [x] State each criterion from the approved plan.

## Tests and checks

- [x] `command` — result

## Documentation

List the Markdown files updated for this change.
```

Only mark an acceptance criterion or check as complete when it was actually verified.

## Remote branch check

Before creating a new pull request, inspect all pull requests for the current head branch with `gh pr list --head <branch> --state all --json number,title,url,state,baseRefName,headRefName`. Include the pull-request number, title, URL, state, and base branch in the inspection.

If a pull request already exists, do not create a duplicate. Ask the user to choose one path:

- Update the existing pull request by keeping its branch and rebasing it onto the intended base branch when needed.
- Create a stacked pull request from a new branch based on the existing pull-request branch, with the existing branch as the new pull request’s base.

If no pull request exists, run the complete applicable test and quality suite, show the user the final summary, ask for remote-action confirmation, push the branch, and create a draft pull request with `gh pr create --draft`.
