from __future__ import annotations

import httpx
import pytest

from job_puller.url_resolution import UnsafeExternalUrlError, fetch_external_page


def public_address(_host: str, _port: int) -> list[str]:
    return ["93.184.216.34"]


def test_fetch_external_page_validates_each_redirect_hop():
    requested = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.host == "apply.example.com":
            return httpx.Response(
                302,
                headers={"location": "https://jobs.lever.co/example/job-123"},
                request=request,
            )
        return httpx.Response(200, text="job", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False) as client:
        result = fetch_external_page(
            "https://apply.example.com/start",
            client=client,
            address_lookup=public_address,
        )

    assert result.final_url == "https://jobs.lever.co/example/job-123"
    assert result.redirect_chain == ("https://jobs.lever.co/example/job-123",)
    assert requested == [
        "https://apply.example.com/start",
        "https://jobs.lever.co/example/job-123",
    ]


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/private",
        "http://[::1]/private",
        "http://metadata.internal/latest",
        "file:///etc/passwd",
        "https://user:password@example.com/apply",
    ],
)
def test_fetch_external_page_rejects_unsafe_destinations_before_request(url):
    class NoRequestClient:
        def get(self, *_args, **_kwargs):
            raise AssertionError("unsafe URL was requested")

    with pytest.raises(UnsafeExternalUrlError):
        fetch_external_page(url, client=NoRequestClient(), address_lookup=public_address)
