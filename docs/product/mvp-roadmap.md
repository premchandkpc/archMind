# ArchMind execution roadmap

**Principle:** validate the problem before expanding the product. The dates below are relative stages; do not pretend calendar completion when a gate has not passed.

## Stage 0 — Baseline and discovery (Weeks 1–2)

### Customer work
- [ ] Recruit 15–20 candidates across architects, site engineers, document controllers/PMC staff, and contractors.
- [ ] Complete 10 interviews using [the discovery plan](market-validation-plan.md).
- [ ] Record anonymized evidence and apply the continue/narrow/stop thresholds.
- [ ] Ask for redacted sample PDFs only with permission.
- [ ] Map one real revision workflow from issuer to receiver.

### Repository and engineering baseline
- [ ] Confirm the focused PDF-inspection CI is green.
- [ ] Run the documented test, lint, and type-check commands; record failures accurately.
- [ ] Fix edge cases in the inspection boundary, including non-finite numeric inputs if any API path accepts numeric values.
- [ ] Keep older AI-platform and native-database experiments out of the MVP dependency path.

### Gate
Proceed only if the discovery thresholds are met. If not, revise or stop the product thesis before adding persistence.

## Stage 1 — Persistence and upload (after a positive discovery gate)

### Design
- [ ] Add versioned PostgreSQL migrations; do not apply the existing schema proposal ad hoc.
- [ ] Define tenant, project, sheet, revision, audit, and outbox ownership and foreign keys.
- [ ] Store PDF bytes in S3-compatible object storage; store object keys and SHA-256 in PostgreSQL.
- [ ] Define idempotency behavior for repeated uploads and duplicate hashes.
- [ ] Preserve the raw revision label; add normalized labels only with explicit rules.
- [ ] Define deletion/retention policy and signed-link/access policy.

### Implementation
- [ ] Persist upload metadata and revision candidates.
- [ ] Add explicit human correction/confirmation endpoints.
- [ ] Enforce request size, page count, MIME/content checks, timeouts, and safe error messages.
- [ ] Ensure tenant/project authorization is checked on every access.
- [ ] Add tests for duplicate uploads, missing metadata, conflicting metadata, and access denial.

### Gate
A user can upload a PDF, inspect it, correct the sheet/revision, and retrieve the same record after restart. Identical bytes do not create duplicate source records unintentionally.

## Stage 2 — Review, approval, and issue transaction

- [ ] Implement revision state transitions: draft → in_review → approved → issued → superseded.
- [ ] Enforce author/approver/issuer separation according to the approved policy.
- [ ] Require a decision/source reference before issue.
- [ ] Issue and supersede within one PostgreSQL transaction.
- [ ] Keep the partial unique index enforcing one current issued revision per sheet.
- [ ] Write audit and outbox records in the same transaction.
- [ ] Implement idempotent issue requests and a clear expected-current-revision check.
- [ ] Add integration tests against real PostgreSQL for concurrent issuers, rollback, stale expected revision, duplicate request, tenant isolation, and role separation.
- [ ] Verify migrations against an empty database and an upgrade path.

### Gate
Concurrent issue attempts cannot leave two current revisions. Failed issuance leaves the previous issue intact and creates no misleading success audit/outbox event.

## Stage 3 — Comparison and distribution (only if customer evidence supports it)

- [ ] Test a manually labeled set of at least 20 representative PDFs before choosing an automated matching strategy.
- [ ] Include scanned, rotated, multi-sheet, inconsistent-title-block, duplicate, and conflicting-label examples.
- [ ] Measure false matches and manual-review rate; optimize safety before recall.
- [ ] Add visual PDF comparison only if users confirm it saves time and can review output quickly.
- [ ] Add a current-status link or QR only if field users demonstrate that it fits their workflow better than existing alternatives.
- [ ] Add distribution/acknowledgment evidence only if buyers identify it as a real gap.
- [ ] If OCR is needed, add it behind the existing conservative matched/unmatched contract.
- [ ] Keep AI summaries as untrusted suggestions; never let them approve or issue revisions.

### Gate
A pilot user can identify the current issue, understand the source of truth, and complete the workflow without a founder explaining each step.

## Stage 4 — Pilot and operational readiness

- [ ] Run a pilot on a real project with permission and agreed data-handling boundaries.
- [ ] Measure time to identify current revision, correction rate, and user-reported incidents.
- [ ] Add backups, restore test, metrics, structured logs, alerting, and documented incident response.
- [ ] Complete security review for tenant isolation, object storage, public links, and audit immutability.
- [ ] Define data export, deletion, retention, and account offboarding.
- [ ] Do not claim production readiness until failure recovery and database behavior have been tested.

## Architecture baseline

- **API:** FastAPI.
- **Metadata and transactions:** PostgreSQL.
- **PDF bytes:** S3-compatible object storage.
- **Reliable async effects:** transactional outbox; add a broker only when measured throughput or operational needs justify it.
- **PDF extraction:** text layer first; OCR only after sample data establishes the need.
- **Testing:** unit tests for parser rules, API tests, and PostgreSQL integration/concurrency tests.

## Explicit non-goals until evidence exists

- Replacing existing construction-management systems.
- QR code as the sole differentiator.
- Native CAD/BIM parsing and editing.
- Custom database or custom version-control engine in the MVP path.
- Kafka, graph infrastructure, or multiple databases without measured need.
- AI-generated compliance or structural-safety decisions.

## Career/time guardrail

Keep interview preparation and employment priorities protected. Limit this project to a small, fixed weekly time budget during discovery. Do not trade sustained interview preparation for speculative features. A disciplined, tested workflow is a stronger engineering portfolio artifact than a large architecture diagram with no users.
