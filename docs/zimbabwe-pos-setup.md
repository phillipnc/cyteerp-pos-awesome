# Zimbabwe POS setup

This branch adds Zimbabwe-oriented multi-currency, customer-credit, return, payment,
and fiscalisation support to POS Awesome for ERPNext v16.

It does not embed a taxpayer certificate, private key, ZIMRA device identity, tax
mapping, exchange rate, or approved-provider credential. Those values are specific
to each registered taxpayer and deployment.

## Currency configuration

1. Create and enable the currencies accepted by the business in ERPNext (for
   example `USD`, `ZWG`, and `ZAR`).
2. Maintain current Currency Exchange records for every required currency pair.
3. Give each Mode of Payment a bank or cash account in the physical currency
   received by that tender.
4. In the POS Profile, enable **Multi-Currency** and configure:
   - **Allow Invoice Currency Selection** if cashiers may change the invoice currency.
   - **Allow Mixed-Currency Tender** if a single invoice may be settled using more
     than one physical currency.
   - **Allowed Currencies** as comma-separated ISO codes.
   - **Manual Rate Tolerance (%)** to limit stale or manipulated client rates.
5. Use a selling Price List whose currency and Item Prices are maintained. UOM-specific
   Item Prices take precedence over conversion-factor pricing.

The invoice retains one accounting currency. Each payment row records the tender
currency, physical tender amount, and tender-to-invoice exchange rate.

Opening and closing shift amounts are also stored per Mode of Payment and physical
currency. Company-currency equivalents are recorded separately. Existing
single-currency shift rows are migrated as company-currency values.

The close-shift screen treats change as physical cash paid in the invoice currency,
which matches the currency used by the SPA when it displays change to the cashier.
If a deployment returns change in a different currency, complete that exchange as a
separate controlled cash movement rather than altering the invoice tender rows.

## Reports and dashboard

The **POS Awesome** workspace provides:

- Number cards for today's invoice count and company-currency gross sales,
  sales after returns, and outstanding POS value.
- Today's POS return count.
- Today's submitted closing-shift count.
- Pending and failed fiscal receipt counts.
- 30-day gross-sales, sales-after-returns, and return-count charts.
- Company-currency sales-by-POS-Profile and sales-by-customer charts.
- A fiscal receipt status chart.

The following standard Script Reports are installed:

- **POS Sales Performance** shows company-currency sales, returns, revenue,
  discounts, tax, quantity, COGS, and gross profit by day, POS Profile, or
  cashier. Gross profit is left blank when complete incoming-rate cost data is
  unavailable.
- **POS Payment Status** shows paid, partly paid, unpaid, return, and
  split-tender invoices with company values and physical tender currencies.
- **POS Item Performance** shows sales, returns, discounts, COGS, and gross
  margin by item, Item Group, or Brand.
- **POS Customer Analytics** shows customer value, average sale, return activity,
  and repeat-customer status.
- **POS Inventory Status** shows POS-warehouse stock health, sales velocity,
  stock cover, reorder levels, projected quantities, and stock value.
- **POS Multi Currency Sales** keeps USD, ZWG, ZAR, and other invoice currencies
  separate and shows ERPNext company-currency equivalents alongside them.
- **POS Tender Reconciliation** groups opening float, tender movements, change,
  returns, and customer Payment Entries by Mode of Payment and physical currency.
  Closed-shift rows also show counted closing amounts and variances; the default
  filter is **Closed**.
- **Zimbabwe Fiscal Receipt Status** lists accepted, pending, failed, and
  unprocessed receipts, including device/day/global numbers, signed company value,
  transaction exposure, and the error backlog.
- **Zimbabwe Fiscal Day Summary** groups fiscal invoices and credit notes by device,
  fiscal day, receipt currency, mapped ZIMRA tax ID, and tax percentage. It is a
  reconstruction from submitted invoices, not an authoritative ZIMRA day-close
  result; reconcile it with the provider/device response before statutory use.

Do not add invoice-currency totals from different currencies. Use either the
currency-specific columns or the explicitly labelled company-currency columns.
The dashboard's cross-currency KPIs use ERPNext `base_*` values.

## Customer accounts and credit

- Customer and Customer Group default Price Lists are applied before the POS Profile
  fallback Price List.
- Credit notes and advances are filtered and validated by customer, company, and
  currency.
- Enable the relevant POS Profile switches for credit sales, partial payments,
  customer-credit returns, and the Customer Payments screen.
- Configure receivable accounts and exchange rates for every invoice currency used.

## Zimbabwe taxpayer data

Maintain these fields before fiscal testing:

- Company: ZIMRA TIN and VAT number.
- Customer: TIN and VAT number when buyer fiscal data is required.
- Item: a four- or eight-digit Zimbabwe HS code. VAT taxpayers must use the HS-code
  length required for the applicable tax treatment.
- Sales Taxes and Charges Templates and Item Tax Templates: the actual tax treatment
  used by ERPNext. The app does not overwrite tax templates with a hard-coded rate.

## Fiscal device

Create one **Zimbabwe Fiscal Device** for each POS Profile.

### Direct FDMS

Configure:

- ZIMRA Device ID, model name, and version.
- Test or Production environment.
- Client certificate and private-key paths relative to the site's `private` directory.
- Tax Mapping JSON from tax percentage to the tax ID returned by the registered
  device configuration.
- Payment Mapping JSON from ERPNext Mode of Payment names to `Cash`, `Card`,
  `MobileWallet`, `Coupon`, or `Credit`.

Use **Get Device Configuration** through the API or server console before the first
fiscal day so the device's receipt verification URL can be stored. Validate all
requests first against the official FDMS test environment.

### External approved provider

Choose **External Provider** and configure its HTTPS endpoint, token, and optional
header JSON. The provider receives an action envelope for `GetConfig`, `GetStatus`,
`OpenDay`, `SubmitReceipt`, and `CloseDay`.

For `SubmitReceipt`, it must return the accepted receipt ID, device signature, server
signature, and either a QR URL/verification code or enough signature data for the app
to derive them using the configured QR base URL.

### Failure and day-close policy

- **Block Invoice When Fiscalisation Fails** defaults on. Keep it enabled unless an
  approved contingency process explicitly permits otherwise.
- **Close Fiscal Day With POS Shift** defaults off because a ZIMRA fiscal day and a
  cashier shift are not always the same operational period.
- Receipt counters advance only after the connector accepts the receipt.
- Re-submission uses the same receipt number and hash until the local transaction is
  committed, supporting FDMS idempotent retries.

## Deployment checklist

Run on the target v16 bench:

```text
bench --site <site> migrate
bench build --app posawesome
bench --site <site> clear-cache
```

Then verify, with test customers and stock:

1. Single-currency cash/card/mobile-wallet sales.
2. Foreign-currency invoices and UOM-specific prices.
3. Mixed-currency settlement and change handling.
4. Credit sales, partial payments, loyalty, advances, and credit-note redemption.
5. Full and multiple partial returns, including serialized and batched items.
6. Offline capture, queue limit, reconnect, and exactly-once sync.
7. Customer Payments capture and reconciliation.
8. M-Pesa callback re-registration with the generated callback token.
9. FDMS open day, invoice, credit note, QR verification, status refresh, and close day.
10. Stock Ledger, General Ledger, Payment Ledger, receivable balances, and shift totals.
11. Each report against the same invoices, tender rows, tax IDs, and fiscal-day
    counters used in the test transactions.
12. Opening and closing drawer counts independently for every Mode of Payment and
    physical currency.

Production use requires successful ERPNext integration testing and acceptance against
the taxpayer's registered ZIMRA device or approved provider. Passing the repository's
static checks alone is not evidence of fiscal certification.
