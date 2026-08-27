from job_puller.normalize import canonical_url, html_to_text, normalized_key


def test_canonical_url_removes_tracking_and_fragment():
    assert (
        canonical_url("HTTPS://Example.com/jobs/1/?utm_source=x&keep=y#top")
        == "https://example.com/jobs/1?keep=y"
    )


def test_canonical_url_removes_lever_source_tracking():
    assert (
        canonical_url("https://jobs.lever.co/acme/1?lever-source=Indeed")
        == "https://jobs.lever.co/acme/1"
    )


def test_canonical_url_collapses_repeated_query_pairs():
    assert (
        canonical_url("https://example.com/job?gh_jid=42&gh_jid=42")
        == "https://example.com/job?gh_jid=42"
    )


def test_html_to_text_removes_script():
    text = html_to_text("<main><h1>Role</h1><script>bad()</script><p>Build APIs</p></main>")
    assert "Role" in text
    assert "Build APIs" in text
    assert "bad" not in text


def test_normalized_key_folds_punctuation():
    assert (
        normalized_key("  Senior Site-Reliability Engineer! ") == "senior site reliability engineer"
    )
