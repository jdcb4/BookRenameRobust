"""Tests for filename builder — all format variants and edge cases."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.sanitiser import build_filename


class TestBuildFilename:
    def test_no_series(self):
        result = build_filename("King, Stephen", "The Shining")
        assert result == "King, Stephen - The Shining.epub"

    def test_series_with_total(self):
        result = build_filename("Sanderson, Brandon", "The Way of Kings",
                                series="The Stormlight Archive", series_index=1.0, series_total=4.0)
        assert result == "Sanderson, Brandon - The Stormlight Archive - Book 1 of 4 - The Way of Kings.epub"

    def test_series_without_total(self):
        result = build_filename("Rothfuss, Patrick", "The Name of the Wind",
                                series="The Kingkiller Chronicle", series_index=1.0)
        assert result == "Rothfuss, Patrick - The Kingkiller Chronicle - Book 1 - The Name of the Wind.epub"

    def test_series_total_zero_treated_as_unknown(self):
        result = build_filename("Author, Test", "Title",
                                series="Series", series_index=1.0, series_total=0)
        assert result == "Author, Test - Series - Book 1 - Title.epub"

    def test_float_index_integer_value(self):
        result = build_filename("Author, Test", "Title",
                                series="Series", series_index=3.0, series_total=5.0)
        assert "Book 3 of 5" in result

    def test_series_without_index_treated_as_no_series(self):
        result = build_filename("Author, Test", "Title", series="Series")
        assert result == "Author, Test - Title.epub"

    def test_empty_author(self):
        result = build_filename("", "The Book")
        assert result == "Unknown Author - The Book.epub"

    def test_empty_title(self):
        result = build_filename("Author, Test", "")
        assert result == "Author, Test - Unknown Title.epub"

    def test_both_empty(self):
        result = build_filename("", "")
        assert result == "Unknown Author - Unknown Title.epub"

    def test_accented_characters_sanitised(self):
        result = build_filename("Garc\u00EDa M\u00E1rquez, Gabriel", "Cien a\u00F1os de soledad")
        assert "Garcia Marquez, Gabriel" in result
        assert "Cien anos de soledad" in result
        assert result.endswith(".epub")

    def test_no_double_spaces(self):
        result = build_filename("Author,  Test", "The  Book  Title")
        assert "  " not in result

    def test_series_index_as_integer(self):
        result = build_filename("A, B", "Title", series="S", series_index=2.0, series_total=10.0)
        assert "Book 2 of 10" in result
        assert "2.0" not in result

    def test_long_title(self):
        long_title = "A Very Long Title That Goes On And On For Many Words"
        result = build_filename("Author, Test", long_title)
        assert long_title in result
        assert result.endswith(".epub")

    def test_special_characters_in_title(self):
        result = build_filename("Author, Test", 'Title: With "Quotes" & More')
        assert result.endswith(".epub")
