"""Tests for queue routing logic."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.router import route_book
from backend.config import settings


class TestRouteBook:
    def setup_method(self):
        """Reset threshold to default before each test."""
        settings.auto_accept_threshold = 0.95

    def _base_data(self, **overrides):
        data = {
            "title_confidence": 0.97,
            "author_confidence": 0.98,
            "overall_confidence": 0.95,
            "quality_ok": True,
            "quality_issues": [],
            "flags": [],
            "proposed_language": "en",
        }
        data.update(overrides)
        return data

    # Auto-accept cases
    def test_auto_accept_high_confidence(self):
        assert route_book(self._base_data()) == "auto_accepted"

    def test_auto_accept_exact_threshold(self):
        assert route_book(self._base_data(
            title_confidence=0.95, author_confidence=0.95
        )) == "auto_accepted"

    def test_auto_accept_custom_threshold(self):
        settings.auto_accept_threshold = 0.90
        assert route_book(self._base_data(
            title_confidence=0.91, author_confidence=0.91
        )) == "auto_accepted"

    # Review cases (below threshold)
    def test_review_low_title_confidence(self):
        assert route_book(self._base_data(title_confidence=0.80)) == "review"

    def test_review_low_author_confidence(self):
        assert route_book(self._base_data(author_confidence=0.80)) == "review"

    def test_review_both_low(self):
        assert route_book(self._base_data(
            title_confidence=0.80, author_confidence=0.80
        )) == "review"

    def test_review_with_flags(self):
        assert route_book(self._base_data(flags=["uncertain series info"])) == "review"

    # Flagged quality cases
    def test_flagged_quality_false(self):
        assert route_book(self._base_data(quality_ok=False)) == "flagged_quality"

    def test_flagged_quality_issues_present(self):
        assert route_book(self._base_data(
            quality_issues=["OCR errors detected"]
        )) == "flagged_quality"

    def test_flagged_quality_overrides_high_confidence(self):
        assert route_book(self._base_data(
            title_confidence=0.99, author_confidence=0.99,
            quality_ok=False
        )) == "flagged_quality"

    def test_flagged_quality_overrides_non_english(self):
        assert route_book(self._base_data(
            quality_ok=False, proposed_language="fr"
        )) == "flagged_quality"

    # Non-English cases
    def test_non_english(self):
        assert route_book(self._base_data(proposed_language="fr")) == "non_english"

    def test_non_english_german(self):
        assert route_book(self._base_data(proposed_language="de")) == "non_english"

    def test_non_english_overrides_auto_accept(self):
        assert route_book(self._base_data(proposed_language="es")) == "non_english"

    def test_english_case_insensitive(self):
        assert route_book(self._base_data(proposed_language="EN")) == "auto_accepted"

    # Edge cases
    def test_none_confidence_goes_to_review(self):
        assert route_book(self._base_data(
            title_confidence=None, author_confidence=None
        )) == "review"

    def test_json_string_quality_issues(self):
        assert route_book(self._base_data(
            quality_issues='["OCR error"]'
        )) == "flagged_quality"

    def test_empty_string_quality_issues(self):
        assert route_book(self._base_data(quality_issues="")) == "auto_accepted"

    def test_json_string_flags(self):
        assert route_book(self._base_data(flags='["flag1"]')) == "review"

    def test_missing_language_defaults_english(self):
        data = self._base_data()
        del data["proposed_language"]
        assert route_book(data) == "auto_accepted"

    # Priority order: flagged_quality > non_english > auto_accept > review
    def test_priority_quality_over_non_english(self):
        assert route_book(self._base_data(
            quality_ok=False, proposed_language="fr"
        )) == "flagged_quality"

    def test_priority_non_english_over_auto_accept(self):
        assert route_book(self._base_data(
            proposed_language="de",
            title_confidence=0.99,
            author_confidence=0.99,
        )) == "non_english"
