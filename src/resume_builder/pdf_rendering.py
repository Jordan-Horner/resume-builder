"""Hardened Playwright PDF rendering and ATS extraction verification."""

from __future__ import annotations

import os
import re
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from pypdf import PdfReader

BAD_GLYPHS = re.compile(r"[\ufb00-\ufb06\ufffd\u25a1]")


def normalized_tokens(value: str) -> list[str]:
    """Create punctuation-insensitive tokens for extraction comparisons."""
    return re.findall(r"[a-z0-9+#.]+", value.casefold())


def tokens_recovered(claim: str, extracted: str) -> bool:
    """Require every claim token to survive extraction, independent of visual column order."""
    required = Counter(normalized_tokens(claim))
    available = Counter(normalized_tokens(extracted))
    return all(available[token] >= count for token, count in required.items())


def extraction_blocks(payload: dict[str, Any]) -> list[tuple[str, str]]:
    """Return each user-visible string that must survive PDF extraction."""
    blocks: list[tuple[str, str]] = []

    def add(owner: str, value: Any) -> None:
        if isinstance(value, str) and value.strip():
            blocks.append((owner, value.strip()))

    candidate = payload.get("candidate")
    if isinstance(candidate, dict):
        for key in ("name", "headline", "phone", "email", "location"):
            add(f"candidate.{key}", candidate.get(key))
        for key in ("linkedin", "github", "portfolio"):
            link = candidate.get(key)
            if isinstance(link, dict):
                add(f"candidate.{key}.display", link.get("display"))
    add("section.summary", "Professional Summary")
    add("summary", payload.get("summary"))
    section_titles = {
        "competencies": "Core Competencies",
        "experience": "Work Experience",
        "projects": "Selected Projects",
        "education": "Education",
        "certifications": "Certifications",
        "skills": "Technical Skills",
    }
    for section in (
        "competencies",
        "experience",
        "projects",
        "education",
        "certifications",
        "skills",
    ):
        items = payload.get(section)
        if not isinstance(items, list):
            continue
        if items:
            add(f"section.{section}", section_titles[section])
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            owner = f"{section}[{index}]"
            for key in (
                "text",
                "company",
                "role",
                "dates",
                "location",
                "name",
                "description",
                "tech",
                "title",
                "org",
                "year",
                "category",
            ):
                add(f"{owner}.{key}", item.get(key))
            for item_index, value in enumerate(item.get("items", [])):
                add(f"{owner}.items[{item_index}]", value)
            for bullet_index, bullet in enumerate(item.get("bullets", [])):
                if isinstance(bullet, dict):
                    add(f"{owner}.bullets[{bullet_index}]", bullet.get("text"))
    return blocks


def audit_pdf(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Require usable text on every page and preservation of every factual block."""
    try:
        reader = PdfReader(path)
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        raise ValueError(f"PDF extraction audit failed: {exc}") from exc
    if not pages:
        raise ValueError("PDF extraction audit failed: document has no pages")
    empty_pages = [index + 1 for index, value in enumerate(pages) if not value.strip()]
    if empty_pages:
        raise ValueError(f"PDF extraction audit failed: pages have no text: {empty_pages}")
    extracted = "\n".join(pages)
    if BAD_GLYPHS.search(extracted):
        raise ValueError("PDF extraction audit failed: unsupported or replacement glyph detected")
    missing: list[str] = []
    for owner, claim in extraction_blocks(payload):
        if not tokens_recovered(claim, extracted):
            missing.append(owner)
    if missing:
        raise ValueError(f"PDF extraction audit failed: factual blocks not recoverable: {missing}")
    return {
        "pages": len(pages),
        "extractable_pages": len(pages),
        "claims_recovered": len(extraction_blocks(payload)),
    }


def render_pdf(
    html_path: Path,
    output: Path,
    payload: dict[str, Any],
    browser: Path | None = None,
) -> dict[str, Any]:
    """Render local HTML in an isolated, network-blocked Playwright browser."""
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ValueError("PDF output requires Playwright; reinstall Resume Builder") from exc

    if browser is not None:
        browser = browser.expanduser().resolve()
        if not browser.is_file():
            raise ValueError(f"browser does not exist: {browser}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=output.parent, prefix=f".{output.name}.", suffix=".tmp.pdf"
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    temporary.unlink(missing_ok=True)
    layout: dict[str, Any] = {}
    try:
        with sync_playwright() as playwright:
            launch: dict[str, Any] = {"headless": True}
            if browser is not None:
                launch["executable_path"] = str(browser)
            engine = playwright.chromium.launch(**launch)
            try:
                context = engine.new_context(java_script_enabled=False)
                try:
                    context.route(
                        "**/*",
                        lambda route: (
                            route.continue_()
                            if route.request.url.startswith(("file:", "data:"))
                            else route.abort()
                        ),
                    )
                    page = context.new_page()
                    page.goto(html_path.as_uri(), wait_until="load")
                    page.evaluate("document.fonts.ready")
                    layout = page.evaluate(
                        """() => {
                          const root = document.documentElement;
                          const body = document.body;
                          const overflowing = [
                            ...document.querySelectorAll('body *:not(.screen-reader-only)')
                          ]
                            .filter((el) => el.scrollWidth > el.clientWidth + 1)
                            .map((el) => el.tagName.toLowerCase() + '.' + el.className)
                            .slice(0, 10);
                          return {
                            horizontal_overflow: root.scrollWidth > root.clientWidth + 1 ||
                              body.scrollWidth > body.clientWidth + 1,
                            overflowing_elements: overflowing
                          };
                        }"""
                    )
                    if layout.get("horizontal_overflow") or layout.get("overflowing_elements"):
                        raise ValueError(f"HTML layout audit failed: {layout}")
                    page.pdf(
                        path=str(temporary),
                        print_background=True,
                        prefer_css_page_size=True,
                        margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
                    )
                finally:
                    context.close()
            finally:
                engine.close()
    except PlaywrightError as exc:
        temporary.unlink(missing_ok=True)
        message = str(exc)
        if "Executable doesn't exist" in message:
            raise ValueError(
                "Playwright Chromium is not installed; run `python -m playwright install chromium`"
            ) from exc
        raise ValueError(f"PDF rendering failed: {exc}") from exc
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    try:
        extraction = audit_pdf(temporary, payload)
        os.replace(temporary, output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return {"layout": layout, "extraction": extraction}
