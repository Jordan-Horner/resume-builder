"""Real-browser regression coverage for the portal's desktop shell."""

from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright


@pytest.mark.browser
def test_jobs_shell_starts_at_and_stays_within_viewport() -> None:
    root = Path(__file__).parents[1]
    tokens = (root / "web/src/tokens.css").read_text()
    styles = (root / "web/src/styles.css").read_text()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 640})
        page.set_content(
            f"<style>{tokens}\n{styles}</style>"
            '<div class="app-shell">'
            '<header class="topbar"><span class="brand">Resume Builder</span>'
            '<nav><a class="nav-link active"><span>Jobs</span></a></nav></header>'
            '<main><div class="page jobs-page">'
            '<section class="search-tools">Search</section>'
            '<div class="jobs-layout"><section class="job-results">Jobs</section></div>'
            "</div></main></div>"
        )

        shell = page.locator(".app-shell").bounding_box()
        topbar = page.locator(".topbar").bounding_box()
        nav_label = page.locator(".nav-link span").bounding_box()
        assert shell is not None and shell["y"] == 0 and shell["height"] == 640
        assert topbar is not None and topbar["y"] == 0
        assert nav_label is not None
        assert abs((nav_label["y"] + nav_label["height"] / 2) - topbar["height"] / 2) <= 1
        assert page.evaluate("document.documentElement.scrollHeight") == 640
        assert (
            page.evaluate("getComputedStyle(document.querySelector('.topbar')).backdropFilter")
            == "none"
        )
        browser.close()
