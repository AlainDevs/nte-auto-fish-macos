"""OpenCV template matching for game UI detection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Literal, Mapping

import cv2
import numpy as np
from PIL import Image


MatchMethod = Literal["ccoeff", "sqdiff"]


@dataclass(frozen=True)
class MatchResult:
    """A single template matching result."""

    template_name: str
    template_path: Path
    confidence: float
    top_left: tuple[int, int]
    center: tuple[int, int]
    size: tuple[int, int]
    capture_size: tuple[int, int]
    method: MatchMethod = "ccoeff"


class TemplateMatcher:
    """Loads and matches UI templates against Pillow screenshots."""

    DEFAULT_TEMPLATES: Mapping[str, str] = {
        "start_fishing": "images/start_fishing.png",
        "catch_now": "images/catch_now.png",
        "time_to_open_map": "images/time_to_open_map.png",
        "return": "images/return.png",
        "failed_catch": "images/failed_catch.png",
        "init_start": "images/init_start.png",
        "time_to_click_start": "images/time_to_click_start.png",
        "phone": "images/phone.png",
    }

    def __init__(
        self,
        templates: Mapping[str, str | Path] | None = None,
        threshold: float = 0.80,
        methods: Mapping[str, MatchMethod] | None = None,
    ) -> None:
        self.threshold = threshold
        source = templates if templates is not None else self.DEFAULT_TEMPLATES
        self.templates: dict[str, Path] = {name: self._resolve_template_path(path) for name, path in source.items()}
        self.methods: dict[str, MatchMethod] = {name: "ccoeff" for name in self.templates}
        if methods is not None:
            for name, method in methods.items():
                if method not in {"ccoeff", "sqdiff"}:
                    raise ValueError("Template match method must be 'ccoeff' or 'sqdiff'")  # pragma: no cover
                self.methods[name] = method
        self._cache: dict[str, np.ndarray] = {}

    @staticmethod
    def _resource_base() -> Path:
        """Return the base path for bundled PyInstaller resources or source files."""
        bundle_path = getattr(sys, "_MEIPASS", None)
        if bundle_path:
            return Path(bundle_path)
        return Path.cwd()  # pragma: no cover

    @classmethod
    def _resolve_template_path(cls, path: str | Path) -> Path:
        template_path = Path(path)
        if template_path.is_absolute():
            return template_path
        bundled = cls._resource_base() / template_path
        if bundled.exists():
            return bundled
        return template_path  # pragma: no cover

    @staticmethod
    def _pil_to_gray(image: Image.Image) -> np.ndarray:
        rgb = image.convert("RGB")
        try:
            array = np.array(rgb)
        finally:
            rgb.close()
        try:
            return cv2.cvtColor(array, cv2.COLOR_RGB2GRAY)
        finally:
            del array

    def _load_template(self, template_name: str) -> np.ndarray:
        if template_name in self._cache:
            return self._cache[template_name]

        path = self.templates[template_name]
        template = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if template is None:
            raise FileNotFoundError(f"Template image not found or unreadable: {path}")  # pragma: no cover
        if template.shape[0] <= 0 or template.shape[1] <= 0:
            raise ValueError(f"Template has invalid size: {path}")  # pragma: no cover

        self._cache[template_name] = template
        return template

    def score(self, image: Image.Image, template_name: str) -> MatchResult | None:
        """Return the best score for a template, regardless of threshold."""
        if template_name not in self.templates:
            raise KeyError(f"Unknown template: {template_name}")  # pragma: no cover

        gray: np.ndarray | None = None
        result: np.ndarray | None = None
        try:
            gray = self._pil_to_gray(image)
            template = self._load_template(template_name)

            template_h, template_w = template.shape[:2]
            image_h, image_w = gray.shape[:2]
            if template_w > image_w or template_h > image_h:
                return None

            method = self.methods.get(template_name, "ccoeff")
            if method == "sqdiff":
                result = cv2.matchTemplate(gray, template, cv2.TM_SQDIFF_NORMED)
                min_value, _, min_location, _ = cv2.minMaxLoc(result)
                confidence = 1.0 - float(min_value)
                location = min_location
            else:
                result = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
                _, max_value, _, max_location = cv2.minMaxLoc(result)
                confidence = float(max_value)
                location = max_location

            top_left = (int(location[0]), int(location[1]))
            center = (top_left[0] + template_w // 2, top_left[1] + template_h // 2)

            return MatchResult(
                template_name=template_name,
                template_path=self.templates[template_name],
                confidence=confidence,
                top_left=top_left,
                center=center,
                size=(template_w, template_h),
                capture_size=(image_w, image_h),
                method=method,
            )
        finally:
            if result is not None:
                del result
            if gray is not None:
                del gray

    def match(
        self,
        image: Image.Image,
        template_name: str,
        threshold: float | None = None,
    ) -> MatchResult | None:
        """Return a match only when confidence is at or above threshold."""
        threshold_value = self.threshold if threshold is None else threshold
        result = self.score(image, template_name)
        if result is not None and result.confidence >= threshold_value:
            return result
        return None

    def match_path(
        self,
        image: Image.Image,
        template_path: str | Path,
        threshold: float | None = None,
    ) -> MatchResult | None:
        path = Path(template_path)  # pragma: no cover
        temporary = TemplateMatcher({path.stem: path}, threshold=self.threshold)  # pragma: no cover
        return temporary.match(image, path.stem, threshold=threshold)  # pragma: no cover
