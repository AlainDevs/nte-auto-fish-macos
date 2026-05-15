from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from nte_fisher.vision import TemplateMatcher


def test_template_matcher_finds_template_center(tmp_path: Path) -> None:
    screenshot = Image.new("RGB", (100, 80), "black")

    template_path = tmp_path / "square.png"
    template = Image.new("RGB", (20, 20), "black")
    template_draw = ImageDraw.Draw(template)
    template_draw.rectangle((2, 2, 17, 17), fill="white")
    template_draw.line((0, 19, 19, 0), fill="gray", width=2)
    template.save(template_path)
    screenshot.paste(template, (30, 20))

    matcher = TemplateMatcher({"square": template_path}, threshold=0.99)

    result = matcher.match(screenshot, "square")


    assert result is not None
    assert result.center == (40, 30)
    assert result.size == (20, 20)
    assert result.capture_size == (100, 80)


def test_template_matcher_returns_none_when_template_larger(tmp_path: Path) -> None:
    screenshot = Image.new("RGB", (10, 10), "black")
    template_path = tmp_path / "large.png"
    Image.new("RGB", (20, 20), "white").save(template_path)
    matcher = TemplateMatcher({"large": template_path})

    assert matcher.score(screenshot, "large") is None
    assert matcher.match(screenshot, "large") is None


def test_template_matcher_below_threshold_returns_none(tmp_path: Path) -> None:
    screenshot = Image.new("RGB", (50, 50), "black")
    template_path = tmp_path / "white.png"
    Image.new("RGB", (10, 10), "white").save(template_path)
    matcher = TemplateMatcher({"white": template_path}, threshold=1.1)

    assert matcher.match(screenshot, "white") is None


def test_template_matcher_supports_sqdiff_method(tmp_path: Path) -> None:
    screenshot = Image.new("RGB", (60, 60), "black")
    template_path = tmp_path / "shape.png"
    template = Image.new("RGB", (12, 12), "black")
    draw = ImageDraw.Draw(template)
    draw.ellipse((2, 2, 9, 9), fill="white")
    template.save(template_path)
    screenshot.paste(template, (22, 18))

    matcher = TemplateMatcher({"shape": template_path}, threshold=0.99, methods={"shape": "sqdiff"})

    result = matcher.match(screenshot, "shape")

    assert result is not None
    assert result.method == "sqdiff"
    assert result.center == (28, 24)
