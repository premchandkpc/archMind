# ArchMind

**PDF-first drawing revision control for construction teams.**

ArchMind helps construction teams answer four questions without guessing:

1. **Which drawing is current?**
2. What changed from the previous revision?
3. Who approved the change?
4. Why was it issued?

ArchMind is a neutral drawing-set control and audit layer. It is not a replacement for AutoCAD, Revit, or Bluebeam.

## What works today

- **PDF inspection API:** `POST /drawing-revisions/inspect` accepts a PDF and extracts text from its pages.
- **Title-block candidates:** identifies explicitly labelled sheet, revision, and project fields.
- **Conservative matching:** missing, conflicting, or ambiguous fields are returned for human review rather than silently guessed.
- **Source hash:** returns a SHA-256 hash for the inspected PDF.
- **Focused tests and CI:** parser and API boundary tests run in the drawing-control workflow.

The inspection endpoint **does not persist uploads, create a revision record, approve a drawing, or issue it**. The database schema is a proposal, not a deployed migration. PDF text extraction does not read scanned pages without a text layer; those need an OCR path or manual handling.

## Product workflow

```text
Upload PDF
   → inspect sheet and revision candidates
   → human confirms or corrects metadata
   → save revision and source file
   → approve with separation of duties
   → issue atomically (one current issued revision per sheet)
   → compare with previous revision
   → append an auditable decision history
```

The MVP should prefer a human-review queue over a confident-looking wrong match. A duplicate file hash should be idempotent, and a second attempt to issue a conflicting revision must be rejected.

## Start here

- [Product plan, discovery sprint, competitor landscape, and MVP roadmap](docs/product/README.md)
- [Drawing-control prototype](docs/drawing-control/mock.html)
- [MVP scope, validation plan, and production gates](docs/drawing-control/README.md)
- [Proposed drawing-revision schema](sql/drawing_revision_control.sql)

## Stack today

- **API:** Python and FastAPI
- **PDF text extraction:** pypdf
- **Tests:** pytest and Ruff
- **Target persistence:** PostgreSQL for metadata, revision state, and audit records; object storage such as S3 for source PDFs
- **Current persistence status:** not implemented in the inspection endpoint

PostgreSQL and object storage are the intended MVP baseline. Additional databases, queues, graph systems, and agent frameworks are not part of the drawing-control critical path unless a demonstrated requirement justifies them.

## What comes next

1. Validate the customer problem with 10 interviews before expanding the product.
2. Add a PostgreSQL migration and persist uploaded-file metadata and revision records; store the PDF in object storage.
3. Build a human review inbox to confirm or correct sheet and revision values.
4. Implement approval and transactional issue semantics, including four-eyes separation and one current issued revision per sheet.
5. Add visual comparison or QR verification only if customer evidence justifies them.

Success is measured by whether a team can reliably identify the current issued sheet and reconstruct who approved it and why, not by the number of infrastructure components in the diagram.

## Experiments outside the MVP

This repository also contains earlier AI-platform and native-database experiments. They are **learning/prototype work, not dependencies of the current drawing-control workflow**. Keep them isolated from the MVP, and do not add their infrastructure to the product path without evidence from users or measurements.

- [Native DB prototype](native-db/README.md): standalone Go storage-engine experiment, not the drawing-control persistence layer.
- [Earlier platform architecture](ARCHITECTURE.md) and [implementation plan](PLAN.md): historical platform work, not the current product roadmap.

## Development

For the current Python package and environment setup, see [pyproject.toml](pyproject.toml) and the drawing-control workflow. The focused CI workflow currently covers the PDF parser and inspection API; it does not establish that the full repository passes all tests or that the PostgreSQL issue transaction is production-ready.

## License

No license has been selected yet. Until one is added, the repository should be treated as all-rights-reserved; do not assume that public visibility grants permission to reuse the code.
