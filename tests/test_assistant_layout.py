"""Real-browser regression coverage for the assistant's responsive shell."""

from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright


@pytest.mark.browser
@pytest.mark.parametrize("width,height", [(1440, 900), (900, 700), (600, 400), (390, 844)])
def test_assistant_floats_without_resizing_workspace(width: int, height: int) -> None:
    css = (Path(__file__).parents[1] / "web/src/assistant/assistant.css").read_text()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})
        page.set_content(
            "<style>body {margin:0}" + css + "</style>"
            '<div class="assistant-layout is-open">'
            '<main class="assistant-workspace">Job inventory</main>'
            '<div class="assistant-dock"><aside class="assistant-panel">Chat</aside></div>'
            "</div>"
        )
        workspace = page.locator(".assistant-workspace").bounding_box()
        dock = page.locator(".assistant-dock").bounding_box()
        assert workspace is not None and workspace["width"] == width
        assert dock is not None
        if width > 480:
            assert dock["width"] == 400
            assert dock["height"] <= 620
            assert dock["x"] > 0 and dock["y"] > 0
            assert dock["x"] + dock["width"] <= width - 16
            assert dock["y"] + dock["height"] <= height - 16
        else:
            assert dock["width"] == width and dock["height"] == height
        page.locator(".assistant-dock").evaluate("element => element.hidden = true")
        assert not page.locator(".assistant-dock").is_visible()
        assert page.locator(".assistant-workspace").is_visible()
        browser.close()
