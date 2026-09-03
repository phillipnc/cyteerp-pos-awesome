<div align="center">
    <img src="https://frappecloud.com/files/pos.png" height="128" alt="POS Awesome">
    <h1>CyteERP POS Awesome</h1>
    <p>A CyteERP-maintained, ERPNext v16-focused distribution of POS Awesome.</p>
</div>

## Project status

This repository starts from
[`WaleedAboHashima/POSAWESOME-16`](https://github.com/WaleedAboHashima/POSAWESOME-16)
and preserves its Git history. CyteERP is extending that v16 foundation with
selected, reviewed ideas and features from
[`defendicon/POS-Awesome-V15`](https://github.com/defendicon/POS-Awesome-V15).

The baseline POS is usable, but the larger CyteERP upgrade is being delivered
in tested phases. See [ROADMAP.md](ROADMAP.md) before relying on a planned
feature. Upstream lineage and integration rules are documented in
[NOTICE.md](NOTICE.md).

## Compatibility

- Frappe Framework: `>=16.0.0,<17.0.0`
- ERPNext: `>=16.0.0,<17.0.0`
- Python: 3.10 or later
- Frontend: Vue 3, Pinia, Vue Router, TypeScript, Tailwind CSS and Vite

ERPNext v15 is intentionally not supported by this distribution.

## Current features

- Fast list and card-based selling
- Batch and serial number handling
- Batch-based pricing
- UOM-specific barcodes and pricing
- Scale and weighted products
- Cash and customer-credit returns
- Credit sales with due dates
- Loyalty points, coupons and POS offers
- Customer and customer-group price lists
- Product bundles and item variants
- Sales Orders from POS
- Customer payments and payment reconciliation
- Selectable invoice currencies and mixed-currency tender
- Currency-separated shift and drawer reconciliation
- Multi-currency sales, tender and Zimbabwe fiscal reports
- POS workspace KPIs, sales trends and fiscal-status dashboard
- Direct ZIMRA FDMS and approved-provider fiscalisation adapters
- M-Pesa support
- Opening and closing shifts
- Offline sale queue and synchronization
- Receipt printing and a bundled POS print format

## Install

From the root of your Frappe bench:

```bash
bench get-app --branch main https://github.com/phillipnc/cyteerp-pos-awesome.git
bench setup requirements
bench build --app posawesome
bench restart
bench --site your.site.name install-app posawesome
bench --site your.site.name migrate
```

For an existing installation:

```bash
cd apps/posawesome
git pull --ff-only
cd ../..
bench setup requirements
bench build --app posawesome
bench --site your.site.name migrate
bench restart
```

Always test upgrades on a staging site and back up the database and files
before migrating production.

## Development

```bash
cd frontend
npm ci
npm run typecheck
npm run build
```

Python changes should pass:

```bash
ruff check --select F .
python -m compileall -q posawesome
```

The generated frontend bundle under `posawesome/public/posawesome` is tracked
so a fresh Frappe installation can build and serve the application reliably.
See [CONTRIBUTING.md](CONTRIBUTING.md) for the branch and review workflow.

## Keyboard shortcuts

- `Ctrl/Cmd + S`: open payments
- `Ctrl/Cmd + X`: submit payments
- `Ctrl/Cmd + D`: remove the first item
- `Ctrl/Cmd + A`: expand the first item
- `Ctrl/Cmd + E`: focus the discount field

## Reporting issues

Use the repository
[issue tracker](https://github.com/phillipnc/cyteerp-pos-awesome/issues) and
include:

- Exact Frappe, ERPNext and app versions
- Browser and operating system
- Steps to reproduce
- Expected and actual results
- Relevant browser-console or server logs

## Upstream projects

- Original POS Awesome project:
  [`yrestom/POS-Awesome`](https://github.com/yrestom/POS-Awesome)
- ERPNext v16 foundation:
  [`WaleedAboHashima/POSAWESOME-16`](https://github.com/WaleedAboHashima/POSAWESOME-16)
- Feature reference:
  [`defendicon/POS-Awesome-V15`](https://github.com/defendicon/POS-Awesome-V15)

CyteERP does not claim ownership of upstream contributions. When upstream code
is ported, its copyright and licensing notices must be retained.

## License

This project is licensed under the GNU General Public License version 3. See
[license.txt](license.txt). Modified and redistributed versions must continue
to comply with the GPL-3.0 terms.
