-- PostgreSQL schema for tenant-scoped drawing revision control.
-- Apply through the project's migration process before enabling issuance APIs.

CREATE TABLE drawing_sheet (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    project_id UUID NOT NULL,
    sheet_number TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, project_id, sheet_number)
);

CREATE TABLE sheet_revision (
    id UUID PRIMARY KEY,
    sheet_id UUID NOT NULL REFERENCES drawing_sheet(id),
    revision_label TEXT NOT NULL,
    file_hash CHAR(64) NOT NULL,
    storage_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('draft', 'in_review', 'approved', 'issued', 'superseded')
    ),
    author_id UUID NOT NULL,
    approved_by UUID,
    decision_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_at TIMESTAMPTZ,
    issued_at TIMESTAMPTZ,
    superseded_at TIMESTAMPTZ,
    CHECK (approved_by IS NULL OR approved_by <> author_id),
    UNIQUE (sheet_id, revision_label)
);

-- The database, not an application-side pre-check, enforces one current issue per sheet.
CREATE UNIQUE INDEX one_issued_revision_per_sheet
    ON sheet_revision (sheet_id)
    WHERE status = 'issued';

CREATE INDEX sheet_revision_history
    ON sheet_revision (sheet_id, created_at DESC);

CREATE TABLE drawing_audit_log (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id UUID NOT NULL,
    project_id UUID NOT NULL,
    sheet_id UUID NOT NULL REFERENCES drawing_sheet(id),
    revision_id UUID NOT NULL REFERENCES sheet_revision(id),
    actor_id UUID NOT NULL,
    action TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    details JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE drawing_outbox (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    project_id UUID NOT NULL,
    event_type TEXT NOT NULL,
    aggregate_id UUID NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at TIMESTAMPTZ
);

-- Call this function inside the application's transaction. Locking the sheet serializes
-- concurrent issue attempts; the partial unique index remains the final invariant.
CREATE OR REPLACE FUNCTION issue_sheet_revision(
    p_revision_id UUID,
    p_actor_id UUID,
    p_expected_current_revision_id UUID
) RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    v_sheet_id UUID;
    v_tenant_id UUID;
    v_project_id UUID;
    v_status TEXT;
    v_author_id UUID;
    v_approved_by UUID;
    v_current_issued_id UUID;
BEGIN
    SELECT sr.sheet_id, ds.tenant_id, ds.project_id, sr.status,
           sr.author_id, sr.approved_by
      INTO v_sheet_id, v_tenant_id, v_project_id, v_status,
           v_author_id, v_approved_by
      FROM sheet_revision sr
      JOIN drawing_sheet ds ON ds.id = sr.sheet_id
     WHERE sr.id = p_revision_id
     FOR UPDATE OF ds, sr;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'revision % not found', p_revision_id
            USING ERRCODE = 'P0002';
    END IF;
    SELECT id INTO v_current_issued_id
      FROM sheet_revision
     WHERE sheet_id = v_sheet_id AND status = 'issued'
     FOR UPDATE;

    IF v_current_issued_id IS DISTINCT FROM p_expected_current_revision_id THEN
        RAISE EXCEPTION 'current issued revision changed; reload history and retry'
            USING ERRCODE = 'serialization_failure';
    END IF;
    IF v_status <> 'approved' THEN
        RAISE EXCEPTION 'only approved revisions can be issued'
            USING ERRCODE = 'check_violation';
    END IF;
    IF v_approved_by IS NULL OR v_approved_by = v_author_id THEN
        RAISE EXCEPTION 'revision requires approval by someone other than its author'
            USING ERRCODE = 'check_violation';
    END IF;
    IF p_actor_id = v_author_id OR p_actor_id = v_approved_by THEN
        RAISE EXCEPTION 'issuer must differ from both author and approver'
            USING ERRCODE = 'check_violation';
    END IF;

    UPDATE sheet_revision
       SET status = 'superseded', superseded_at = now()
     WHERE sheet_id = v_sheet_id AND status = 'issued';

    UPDATE sheet_revision
       SET status = 'issued', issued_at = now()
     WHERE id = p_revision_id;

    INSERT INTO drawing_audit_log (
        tenant_id, project_id, sheet_id, revision_id, actor_id, action, details
    ) VALUES (
        v_tenant_id, v_project_id, v_sheet_id, p_revision_id, p_actor_id,
        'revision.issued',
        jsonb_build_object('revision_label', (
            SELECT revision_label FROM sheet_revision WHERE id = p_revision_id
        ))
    );

    INSERT INTO drawing_outbox (
        id, tenant_id, project_id, event_type, aggregate_id, payload
    ) VALUES (
        gen_random_uuid(), v_tenant_id, v_project_id, 'revision.issued', p_revision_id,
        jsonb_build_object('sheet_id', v_sheet_id, 'revision_id', p_revision_id)
    );
END;
$$;
