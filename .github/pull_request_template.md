## Summary

Describe the user problem and the implemented change.

## Validation

- [ ] `npm run typecheck`
- [ ] `npm run build`
- [ ] `ruff check --select F .`
- [ ] `python -m compileall -q posawesome`
- [ ] Relevant Frappe/ERPNext v16 tests
- [ ] Manual POS workflow test

## Accounting, Stock and Offline Impact

Describe any effect on GL entries, payments, stock ledger, serial/batch
allocation, shifts or offline synchronization.

## Upstream Source

For a feature port, provide the upstream repository, commit and files used.
Explain the changes made for ERPNext v16 and confirm that attribution was
retained.

## Migration and Rollback

List patches, custom fields, DocTypes and the rollback procedure. Write
`Not applicable` when the change has no schema or data impact.
