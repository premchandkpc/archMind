# PDF-first drawing control MVP

## Product thesis

ArchMind is not a better CAD editor. It is the neutral record of which drawing is current, what changed, why it changed, and who approved and issued it.

**First user:** the architect or document controller who issues drawing sets. **Receiver:** site engineer, contractor, or consultant who needs to trust that the copy in hand is current. Sell to the issuer; let the issued record spread to receivers.

## Problem hypothesis to validate

The initial hypothesis is that drawing revisions are circulated through email, WhatsApp, and shared folders, while revision clouds and filenames are not a reliable source of truth. Wrong-version work can cause rework, delays, and disputes. These are hypotheses, not validated customer findings yet.

Interview 10 architects, site engineers, and contractors before committing to the next product slice. Ask only:

> Walk me through the last time a wrong drawing was used. What happened and what did it cost?

Do not pitch ArchMind. Record the last incident, current workaround, frequency, cost, people involved, and who owns the budget. Rank use cases using interview evidence, not founder enthusiasm.

## MVP workflow

1. Upload or forward a PDF drawing set.
2. Extract explicit title-block labels per page: sheet number, revision label, and project name.
3. Automatically match only when the sheet number and revision label are explicitly identified. Route scanned pages, missing labels, and ambiguous matches to a human review inbox.
4. Compare two PDF revisions visually and let a reviewer confirm changes.
5. Attach the source request or meeting decision, author, approver, and issue event.
6. Issue the approved revision transactionally. Supersede the previous issue in the same transaction.

## API currently implemented

**POST /drawing-revisions/inspect** accepts one PDF upload and returns:
- page count and SHA-256 content hash;
- per-page sheet number, revision label, and project-name candidates;
- matched/unmatched status, confidence, and missing fields;
- explicit limitations.

It uses text extraction only. Scanned PDFs are unmatched until OCR is added. The endpoint does not persist revisions or issue drawings.

## Database invariant

`sql/drawing_revision_control.sql` defines tenant/project-scoped sheets and revision records, plus the partial unique index:

```sql
CREATE UNIQUE INDEX one_issued_revision_per_sheet
    ON sheet_revision (sheet_id)
    WHERE status = 'issued';
```

The `issue_sheet_revision` PostgreSQL function locks the sheet, requires an approved revision, enforces separation between author, approver, and issuer, supersedes the previous issue, issues the new revision, and writes audit/outbox records within the caller's transaction. The unique index remains the final protection against concurrent issue attempts.

The SQL has been added as a schema proposal, not applied to a live database. A production migration and PostgreSQL concurrency tests are required before the issuance workflow is exposed.

## Trust boundaries

- OCR or parsing output is a candidate, never authoritative identity by itself.
- Never silently assign a sheet number or revision when labels are missing.
- AI may summarize verified changes, but cannot approve code compliance or structural safety.
- The audit trail must preserve actor, time, source hash, revision identity, decision reference, and issue event.
- Tenant and project scope must be applied to every lookup and uniqueness rule.
- A correction to an issued drawing creates a new revision; do not rewrite issued history.

## Metrics

- **North star:** percentage of issued revisions compared and reviewed before issue.
- Leading indicators: unmatched-page rate, title-block correction rate, time to identify the current issue, and time spent comparing a revision.
- Business validation: number of interviewees who can quantify a recent incident, current spend/workaround, and willingness to pay for a concrete workflow.

Do not optimize upload count. Uploads are easy to produce and can be completely unrelated to value.

## Not in the first release

Native CAD plugins, Revit/IFC object graphs, Blender/FreeCAD adapters, automatic compliance decisions, semantic merging, and a custom version-control engine.

## Before production

1. Interview 10 target users and map one real project's revision circulation.
2. Test title-block extraction against a representative set of real PDFs, including scanned, rotated, and inconsistent title blocks.
3. Add OCR behind the same conservative matched/unmatched contract.
4. Apply the schema through a migration and add real PostgreSQL tests for concurrent issuance, failed transactions, author/approver/issuer separation, and tenant isolation.
5. Build PDF image diff only after validating that users need it and can review its results quickly.
