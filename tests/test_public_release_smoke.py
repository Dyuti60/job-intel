from scripts.public_release_smoke import first_job_detail_path


def test_smoke_selects_one_job_detail_when_available() -> None:
    assert first_job_detail_path(
        {"items": [{"id": "job-123", "display_name": "Grade IV Staff"}]}
    ) == (
        "/jobs/assam/job-123/grade-iv-staff"
    )


def test_smoke_skips_detail_when_no_public_job_exists() -> None:
    assert first_job_detail_path({"items": []}) is None
    assert first_job_detail_path({"unexpected": []}) is None
