from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture the reviewed Phoenix resume page for the public case study."
    )
    parser.add_argument(
        "--html",
        type=Path,
        default=Path("examples/phoenix-wright/workspace/build/senior-defense-attorney.html"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/assets/phoenix-wright-resume.jpg"),
    )
    args = parser.parse_args()
    html_path = args.html.resolve(strict=True)
    output_path = args.output.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1200, "height": 1200}, device_scale_factor=2)
        page.route(
            "**/*",
            lambda route: (
                route.continue_() if route.request.url.startswith("file:") else route.abort()
            ),
        )
        page.goto(html_path.as_uri(), wait_until="load")
        page.evaluate("document.fonts.ready")
        resume = page.locator("main.page")
        resume_box = resume.bounding_box()
        last_block_box = resume.locator(":scope > :last-child").bounding_box()
        if resume_box is None or last_block_box is None:
            raise RuntimeError("Could not measure the rendered resume")

        content_height = last_block_box["y"] + last_block_box["height"] - resume_box["y"]
        page.screenshot(
            path=str(output_path),
            type="jpeg",
            quality=92,
            clip={
                "x": resume_box["x"],
                "y": resume_box["y"],
                "width": resume_box["width"],
                "height": min(resume_box["height"], content_height + 48),
            },
        )
        browser.close()

    print(f"Captured {output_path.relative_to(Path.cwd())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
