import httpx

from job_puller.liveness import verify_job_liveness


def job(**updates):
    value = {
        "url": "https://boards.example/jobs/123",
        "providers": ["greenhouse"],
    }
    value.update(updates)
    return value


def test_direct_ats_404_is_closed():
    transport = httpx.MockTransport(lambda request: httpx.Response(404, request=request))

    result = verify_job_liveness(job(), 5, transport=transport)

    assert result["status"] == "closed"


def test_direct_ats_redirect_is_reported():
    def respond(request):
        if request.url.path == "/jobs/123":
            return httpx.Response(302, headers={"location": "/jobs/456"}, request=request)
        return httpx.Response(200, request=request)

    result = verify_job_liveness(job(), 5, transport=httpx.MockTransport(respond))

    assert result["status"] == "redirected"
    assert str(result["final_url"]).endswith("/jobs/456")


def test_aggregator_only_job_is_not_guessed_closed():
    result = verify_job_liveness(job(providers=["linkedin"]), 5)

    assert result["status"] == "inconclusive"
