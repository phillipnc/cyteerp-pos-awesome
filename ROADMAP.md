# CyteERP POS Awesome Roadmap

This roadmap distinguishes released functionality from planned upstream
feature ports. A checkbox is marked only after the feature has been adapted to
the v16 architecture, tested and documented.

## Phase 0 — Repository Baseline

- [x] Preserve the ERPNext v16 foundation and Git history
- [x] Establish CyteERP repository metadata and upstream attribution
- [x] Add automated frontend and Python validation
- [x] Adopt `main` and `develop` branch conventions
- [ ] Publish the first signed/tagged CyteERP release

## Phase 1 — Reliability

- [ ] Expand backend tests for invoices, returns and discounts
- [ ] Add duplicate-safe invoice submission
- [ ] Harden offline queue replay and recovery
- [ ] Add multi-terminal stock refresh
- [ ] Add documented staging and upgrade checks

## Phase 2 — Payments

- [ ] Multi-currency tender and change handling
- [ ] Automatic payment allocation
- [ ] Extended customer payment reconciliation
- [ ] Supplier and employee payments
- [ ] Gift-card issue, top-up and redemption
- [ ] M-Pesa callback security and replay protection review

## Phase 3 — Inventory and Procurement

- [ ] Multi-batch allocation and row splitting
- [ ] Barcode and label printing
- [ ] Item quick-edit controls
- [ ] Purchase Orders from POS
- [ ] Purchase Receipts and Purchase Invoices from POS
- [ ] Supplier creation and payment controls

## Phase 4 — Cashier Operations

- [ ] Supervisor role and permissions
- [ ] Cashier PIN switching and terminal locking
- [ ] Cash expenses and deposits
- [ ] Shift-level audit trail and dashboard
- [ ] Controlled submitted-invoice corrections

## Phase 5 — Hardware and Distribution

- [ ] QZ Tray integration
- [ ] Raw ESC/POS receipt printing
- [ ] ZPL/EPL barcode printing
- [ ] Docker deployment definitions
- [ ] Evaluate an Electron desktop shell

## Porting Standard

Each port must:

1. Name the upstream repository and exact source commit.
2. Be redesigned for Frappe and ERPNext v16 instead of copying v15
   compatibility code blindly.
3. Include permission, accounting, inventory and offline tests where relevant.
4. Include patches and rollback guidance for schema changes.
5. Pass CI and staging verification before merging into `main`.
