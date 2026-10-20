# ArchMind: product requirements

**Status:** hypothesis / discovery stage  
**Last updated:** 2026-10-20  
**Product:** PDF-first drawing revision control for construction teams

## 1. Summary

ArchMind aims to help construction teams answer:

1. Which drawing revision is currently issued for this sheet?
2. What changed from the previous revision?
3. Who approved and issued it?
4. What decision or request justified the issue?

ArchMind is a neutral control and audit layer around PDF drawing sets. It is not a CAD editor or a replacement for established construction-management platforms.

## 2. Customer and user hypotheses

- **Initial buyer hypothesis:** architect, design consultant, document controller, or project-management consultant responsible for issuing drawing sets.
- **Recipients:** site engineers, contractors, subcontractors, and consultants who need to identify the correct revision.
- **Potential problem:** files circulate through email, messaging apps, downloads, and shared folders; recipients may not reliably know whether a copy is current.
- **Validation status:** not validated. Interview evidence is required before treating these as facts.

## 3. Job to be done

When a drawing changes, the responsible team needs to issue the approved revision and provide recipients with a trustworthy way to identify the current version and reconstruct the decision history, without relying on filenames or memory.

## 4. Core workflow

1. Upload a PDF drawing or drawing set.
2. Inspect pages and extract explicit title-block candidates.
3. Ask a human to confirm or correct sheet and revision metadata when needed.
4. Persist the source file and revision metadata.
5. Submit the revision for review.
6. Approve it using separation of duties.
7. Issue it transactionally; supersede the prior issued revision for that sheet.
8. Compare the new revision with the previous one and let a reviewer confirm the differences.
9. Preserve an append-only audit trail and an outbox event for reliable downstream delivery.
10. Let recipients check current status and, if the workflow supports it, record receipt or acknowledgment.

## 5. MVP scope

### Required

- PDF upload with strict size/page limits and content hashing.
- Per-page title-block candidate extraction.
- Explicit unmatched/manual-review behavior for scanned, missing, conflicting, or ambiguous labels.
- Idempotency for repeated uploads of identical content.
- PostgreSQL persistence for projects, sheets, revisions, approvals, issue state, and audit records.
- Object storage for PDF bytes.
- Human review queue.
- Approval and issue transitions enforced by server-side authorization and database invariants.
- Exactly one current issued revision per sheet, enforced by PostgreSQL.
- Append-only audit records with actor, timestamp, source hash, decision reference, and revision identity.
- Integration tests against real PostgreSQL for concurrency and transaction rollback.
- Operational logs and clear error responses.

### Conditional, after discovery

- Visual PDF comparison and overlay.
- OCR for scanned PDFs.
- QR codes or public verification links.
- Email ingestion and distribution acknowledgments.
- AI-generated change summaries.

These features are not assumed to be differentiators. Prioritize them only when customer evidence shows they solve a frequent, costly problem better than current alternatives.

### Explicitly out of scope

- Replacing AutoCAD, Revit, Bluebeam, Procore, or PlanRadar.
- Native CAD/BIM editing.
- Automated structural-safety or code-compliance decisions.
- Automatic approval based on AI.
- A custom version-control engine.
- Introducing Kafka, graph databases, or agent frameworks without a demonstrated need.

## 6. Domain rules and invariants

- A revision's extracted metadata is a candidate until confirmed.
- Missing or conflicting identifiers must not be silently guessed.
- A content hash identifies identical bytes, not necessarily identical business meaning.
- Revision labels must preserve the original raw label even if a normalized form is added.
- An issued revision is immutable; corrections create a new revision.
- Author and approver must differ. The issuer must follow the project's approved separation-of-duties policy.
- Issuance and supersession happen in one database transaction.
- A partial unique index enforces at most one `issued` revision per sheet.
- Tenant and project authorization is applied to every read and write.
- Repeated commands must be idempotent or return a clear conflict.
- Audit history must not be silently rewritten.
- External notifications should be emitted from a transactional outbox, not sent inside the issue transaction.

## 7. Success metrics

### Product outcome

- Percentage of issued revisions compared and reviewed before issue, if comparison is validated as useful.
- Time for a site user to determine the current issued revision.
- Rate of wrong-revision incidents reported by pilot users.

### Workflow quality

- Percentage of pages requiring manual correction.
- False-match rate on a labeled PDF sample.
- Time from upload to confirmed metadata.
- Failed or conflicting issue attempts.
- Percentage of recipients who can verify a drawing without help.

### Business validation

- Number of interviewees describing a recent, concrete incident.
- Cost or time of the current workaround.
- Identified buyer and budget owner.
- Number of users who commit to a pilot with real sample documents.
- Paid pilot or credible willingness-to-pay evidence.

Do not optimize upload count alone. It does not prove that the workflow creates value.

## 8. Risks

| Risk | Mitigation |
|---|---|
| Existing platforms already solve the use case | Interview customers about the exact unsolved workflow before building. |
| Metadata extraction confidently returns the wrong sheet | Conservative matching and mandatory human confirmation when ambiguous. |
| Concurrent issue operations produce conflicting current revisions | Row locking, transaction semantics, and a partial unique index with real PostgreSQL tests. |
| Scanned and inconsistent PDFs are common | Measure the manual-review rate on a representative sample before choosing OCR investment. |
| Cross-company sharing exposes confidential drawings | Explicit project access, short-lived or revocable links, audit logs, and security review. |
| QR is easy for incumbents to copy | Treat QR as an interface option, not the core value proposition. |
| Scope overwhelms a solo builder | One validated workflow, one persistence layer, and staged release gates. |

## 9. Release gates

Do not expose production issuance until migrations, authorization, audit behavior, and PostgreSQL concurrency tests pass. Do not invest in OCR, QR, visual diff, or AI summaries until discovery and sample-document tests justify the work.
