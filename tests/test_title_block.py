"""Tests for conservative PDF title-block parsing."""

from civilmind.drawing_control.title_block import parse_title_block_text


def test_parses_explicit_sheet_revision_and_project_labels() -> None:
    result = parse_title_block_text(
        "Project: Courtyard House\nSheet No: A-101\nRevision: R5\nIssued for Construction"
    )

    assert result.sheet_number == "A-101"
    assert result.revision_label == "R5"
    assert result.project_name == "Courtyard House"
    assert result.status == "matched"
    assert result.confidence == 0.95
    assert result.missing_fields == ()


def test_missing_revision_is_sent_to_human_review() -> None:
    result = parse_title_block_text("Project: Courtyard House\nSheet Number: A101")

    assert result.sheet_number == "A101"
    assert result.revision_label is None
    assert result.status == "unmatched"
    assert "revision_label" in result.missing_fields


def test_scanned_or_unextractable_page_is_unmatched() -> None:
    result = parse_title_block_text("")

    assert result.status == "unmatched"
    assert result.confidence == 0.0
    assert set(result.missing_fields) == {"sheet_number", "revision_label", "project_name"}


def test_unlabelled_code_is_not_assumed_to_be_sheet_number() -> None:
    result = parse_title_block_text("Notes: use A101 finish specification. Rev: 5")

    assert result.sheet_number is None
    assert result.status == "unmatched"



def test_revision_no_label_is_skipped_before_revision_value() -> None:
    result = parse_title_block_text("Sheet No: A101\nRevision No: R5")

    assert result.status == "matched"
    assert result.sheet_number == "A101"
    assert result.revision_label == "R5"
    assert result.candidate_revision_labels == ("R5",)


def test_revision_placeholder_is_not_accepted_as_a_candidate() -> None:
    result = parse_title_block_text("Sheet No: A101\nRevision: N/A")

    assert result.status == "unmatched"
    assert result.sheet_number == "A101"
    assert result.revision_label is None
    assert result.candidate_revision_labels == ()
    assert "revision_label" in result.missing_fields


def test_conflicting_sheet_candidates_require_human_review() -> None:
    result = parse_title_block_text(
        "Sheet No: A-101\nSheet No: S-202\nRevision: R5"
    )

    assert result.status == "unmatched"
    assert result.sheet_number is None
    assert result.candidate_sheet_numbers == ("A-101", "S-202")
    assert result.ambiguous_fields == ("sheet_number",)


def test_conflicting_revision_candidates_require_human_review() -> None:
    result = parse_title_block_text(
        "Sheet Number: A101\nRevision: R4\nRevision Number: R5"
    )

    assert result.status == "unmatched"
    assert result.revision_label is None
    assert result.candidate_revision_labels == ("R4", "R5")
    assert result.ambiguous_fields == ("revision_label",)
