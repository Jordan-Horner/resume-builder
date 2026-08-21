from resume_builder.artifact_status import ArtifactStatus


def test_artifact_status_preserves_the_json_report_shape() -> None:
    status = ArtifactStatus(
        status="stale",
        path="build/example.json",
        reasons=("source changed",),
        details={"warnings": ["review this"]},
    )

    assert status.as_dict() == {
        "status": "stale",
        "path": "build/example.json",
        "reasons": ["source changed"],
        "warnings": ["review this"],
    }
