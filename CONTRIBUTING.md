# Contributing to CyteERP POS Awesome

Thanks for helping make POS Awesome better! This document explains how to set
up a development environment and get your contribution merged.

## Code of Conduct

Be respectful. Keep criticism about code, not people.

## Getting Started

1. Fork the repository and clone your fork into your bench:

   ```bash
   bench get-app https://github.com/your-account/cyteerp-pos-awesome.git
   ```

2. Install frontend dependencies:

   ```bash
   cd apps/posawesome/frontend
   npm ci
   ```

3. Start developing:

   ```bash
   # terminal 1 — backend + desk
   bench start

   # terminal 2 — frontend with hot reload
   cd apps/posawesome/frontend && npm run dev
   ```

## Before You Open a Pull Request

Run the checks — a PR that fails these will not be merged:

```bash
cd frontend
npm run typecheck   # vue-tsc, strict
npm run build       # regenerates posawesome/public/posawesome and www/posawesome.html
```

Python changes should pass `ruff check --select F .` and
`python -m compileall -q posawesome`. The broader inherited lint backlog will
be tightened incrementally without mixing formatting-only changes into feature
ports.

Commit the regenerated build output together with your source changes: the
built bundle is tracked on purpose so fresh clones work without Node.

## How We Work

- **Branch from `develop`.** `main` is the production-ready branch.
- **One topic per PR.** Small, focused PRs get reviewed fast.
- **Commits:** short imperative subject line, blank line, then *why* if it is
  not obvious from the diff. No AI attribution trailers.
- **Tests** are welcome; doctypes ship test skeletons under
  `posawesome/posawesome/doctype/*/test_*.py`.
- **Screenshots or screen recordings** for anything user-facing.

## Reporting Bugs

Open a GitHub issue [here](https://github.com/phillipnc/cyteerp-pos-awesome/issues/new/choose)
and include:

- ERPNext / Frappe versions (`bench version`)
- Steps to reproduce, expected vs actual behaviour
- Console errors and, for print issues, the browser used

## Feature Requests

Open an issue tagged `feature` describing the problem you are solving, who has
it, and how a cashier would use it. POS features live or die at the till, so
argue from the counter, not the conference room.

## License

By contributing you agree that your contributions are licensed under the GNU
General Public License v3, same as the rest of the project.

## Porting Upstream Features

Do not copy an entire upstream branch or directory into this repository.
Feature ports must:

- Identify the upstream repository and commit in the pull request.
- Retain applicable copyright and GPL notices.
- Separate ERPNext v15 compatibility code from the v16 implementation.
- Include tests for accounting, stock, permissions or offline behaviour.
- Include migration and rollback notes when DocTypes or custom fields change.
- Pass the frontend build and Python validation checks.
