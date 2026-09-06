from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx


class ExternalUrlError(RuntimeError):
    """Raised when an external application URL cannot be fetched safely."""


class UnsafeExternalUrlError(ExternalUrlError):
    """Raised before a request when an external URL could reach a private service."""


@dataclass(frozen=True, slots=True)
class ResolvedExternalPage:
    requested_url: str
    final_url: str
    redirect_chain: tuple[str, ...]
    response: httpx.Response


AddressLookup = Callable[[str, int], Iterable[str]]


def _lookup_addresses(host: str, port: int) -> set[str]:
    try:
        answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ExternalUrlError(f"could not resolve external application host: {host}") from exc
    return {str(answer[4][0]) for answer in answers}


def _validate_public_url(url: str, address_lookup: AddressLookup) -> None:
    try:
        parsed = urlsplit(url)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise UnsafeExternalUrlError("external application URL is malformed") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UnsafeExternalUrlError("external application URL must use HTTP or HTTPS")
    if parsed.username or parsed.password:
        raise UnsafeExternalUrlError("external application URL must not contain credentials")

    host = parsed.hostname.casefold().rstrip(".")
    if (
        host == "localhost"
        or host.endswith((".localhost", ".local", ".internal", ".home", ".lan"))
        or "." not in host
    ):
        raise UnsafeExternalUrlError(f"external application host is not public: {host}")

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        addresses = set(address_lookup(host, port))
        if not addresses:
            raise ExternalUrlError(f"external application host has no addresses: {host}") from None
    else:
        addresses = {str(literal)}

    for address in addresses:
        try:
            parsed_address = ipaddress.ip_address(address)
        except ValueError as exc:
            raise ExternalUrlError(
                f"external application host returned an invalid address: {host}"
            ) from exc
        if not parsed_address.is_global:
            raise UnsafeExternalUrlError(
                f"external application host resolved to a non-public address: {host}"
            )


def fetch_external_page(
    url: str,
    *,
    timeout: float = 30,
    max_redirects: int = 5,
    client: httpx.Client | None = None,
    address_lookup: AddressLookup | None = None,
) -> ResolvedExternalPage:
    """Fetch an external application page while validating every redirect hop."""

    if max_redirects < 0:
        raise ValueError("max_redirects must be non-negative")
    lookup = address_lookup or _lookup_addresses
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout, follow_redirects=False)

    requested_url = url.strip()
    current = requested_url
    chain: list[str] = []
    try:
        for hop in range(max_redirects + 1):
            _validate_public_url(current, lookup)
            try:
                response = client.get(
                    current,
                    headers={
                        "Accept-Language": "en-US,en;q=0.9",
                        "User-Agent": "JobPuller/0.1 (+local personal inventory)",
                    },
                )
            except httpx.HTTPError as exc:
                raise ExternalUrlError(f"external application request failed: {exc}") from exc
            if response.is_redirect:
                if hop >= max_redirects:
                    raise ExternalUrlError("external application URL exceeded the redirect limit")
                location = response.headers.get("location", "").strip()
                if not location:
                    raise ExternalUrlError("external application redirect omitted its destination")
                current = urljoin(current, location)
                chain.append(current)
                continue
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise ExternalUrlError(
                    f"external application destination returned HTTP {response.status_code}"
                ) from exc
            return ResolvedExternalPage(requested_url, current, tuple(chain), response)
    finally:
        if owns_client:
            close = getattr(client, "close", None)
            if close is not None:
                close()

    raise ExternalUrlError("external application URL could not be resolved")
