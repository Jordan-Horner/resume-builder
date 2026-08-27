from job_puller.normalize import canonical_url, html_to_text, normalized_key


def test_canonical_url_removes_tracking_and_fragment():
    assert (
        canonical_url("HTTPS://Example.com/jobs/1/?utm_source=x&keep=y#top")
        == "https://example.com/jobs/1?keep=y"
    )


def test_html_to_text_removes_script():
    text = html_to_text("<main><h1>Role</h1><script>bad()</script><p>Build APIs</p></main>")
    assert "Role" in text
    assert "Build APIs" in text
    assert "bad" not in text


def test_normalized_key_folds_punctuation():
    assert normalized_key("  Senior Site-Reliability Engineer! ") == "senior site reliability engineer"
