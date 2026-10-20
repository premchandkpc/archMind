# ArchMind product planning

This directory contains the working plan for validating and building ArchMind's PDF-first drawing revision-control product.

## Read in this order

1. [Product thesis and MVP PRD](PRD.md) — target user, problem hypothesis, scope, workflow, risks, and acceptance criteria.
2. [Market and competitor landscape](competitor-landscape.md) — existing alternatives and hypotheses worth testing.
3. [Customer discovery plan](market-validation-plan.md) — a ten-interview research sprint, script, and decision rules.
4. [Interview tracker](interview-tracker-template.md) — copy one template per interview; do not put confidential project details in public Git.
5. [Execution roadmap](mvp-roadmap.md) — staged technical work and release gates.

## Current truth

- The working product direction is PDF-first drawing revision control.
- `POST /drawing-revisions/inspect` inspects PDF text and returns title-block candidates and a content hash.
- Inspection does not persist uploads, approve drawings, or issue revisions.
- The SQL schema is a proposal and is not applied to a live database.
- Customer interviews and willingness-to-pay are **not yet validated**.
- Competitors already offer QR-based drawing verification. QR alone is not a defensible product thesis.

## Working rules

- Keep observed facts, customer quotes, hypotheses, and decisions separate.
- Do not claim interviews, pilots, or market validation until they have happened.
- Do not build the next stage merely because it is technically interesting.
- Keep the MVP on FastAPI, PostgreSQL, and object storage unless evidence justifies a change.
- Treat drawing identity and revision extraction as candidates requiring human confirmation when ambiguous.
- Keep AI-platform and native-database experiments outside the MVP critical path.
