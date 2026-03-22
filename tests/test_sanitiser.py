"""Tests for ASCII sanitiser — substitution map, stripping, and field diffing."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.sanitiser import sanitise_string, sanitise_all_fields


class TestSanitiseString:
    def test_plain_ascii_unchanged(self):
        result, subs = sanitise_string("Hello World")
        assert result == "Hello World"
        assert subs == []

    def test_smart_quotes_replaced(self):
        result, subs = sanitise_string("\u201CHello\u201D")
        assert result == '"Hello"'
        assert len(subs) == 2

    def test_single_smart_quotes(self):
        result, _ = sanitise_string("\u2018it\u2019s\u2019")
        assert result == "'it's'"

    def test_em_dash_replaced(self):
        result, subs = sanitise_string("word\u2014word")
        assert result == "word-word"
        assert len(subs) == 1

    def test_en_dash_replaced(self):
        result, _ = sanitise_string("2020\u20132024")
        assert result == "2020-2024"

    def test_ellipsis_replaced(self):
        result, _ = sanitise_string("Wait\u2026")
        assert result == "Wait..."

    def test_accented_e(self):
        result, _ = sanitise_string("caf\u00E9")
        assert result == "cafe"

    def test_accented_u(self):
        result, _ = sanitise_string("na\u00EFve")
        assert result == "naive"

    def test_n_tilde(self):
        result, _ = sanitise_string("Espa\u00F1a")
        assert result == "Espana"

    def test_c_cedilla(self):
        result, _ = sanitise_string("fran\u00E7ais")
        assert result == "francais"

    def test_o_slash(self):
        result, _ = sanitise_string("Kj\u00F8ller")
        assert result == "Kjoller"

    def test_ligature_ae(self):
        result, _ = sanitise_string("\u00E6sthetic")
        assert result == "aesthetic"

    def test_ligature_oe(self):
        result, _ = sanitise_string("\u0153uvre")
        assert result == "oeuvre"

    def test_eszett(self):
        result, _ = sanitise_string("Stra\u00DFe")
        assert result == "Strasse"

    def test_strip_remaining_non_ascii(self):
        result, subs = sanitise_string("Hello\u2603World")  # snowman
        assert result == "HelloWorld"
        assert any("stripped" in s[2] for s in subs)

    def test_normalise_whitespace(self):
        result, _ = sanitise_string("  Hello   World  ")
        assert result == "Hello World"

    def test_empty_string(self):
        result, subs = sanitise_string("")
        assert result == ""
        assert subs == []

    def test_mixed_substitutions(self):
        result, subs = sanitise_string("\u201CHello\u201D \u2014 caf\u00E9")
        assert result == '"Hello" - cafe'
        assert len(subs) == 4

    def test_unicode_decomposition_fallback(self):
        # Characters not in map but decomposable
        result, _ = sanitise_string("\u0101")  # a with macron
        assert result == "a"

    def test_substitution_tracking(self):
        _, subs = sanitise_string("\u2018test\u2019")
        assert len(subs) == 2
        assert all(len(s) == 3 for s in subs)  # (orig, replacement, description)


class TestSanitiseAllFields:
    def test_sanitises_string_fields(self):
        data = {"proposed_title": "caf\u00E9", "proposed_author": "na\u00EFve", "proposed_series_index": 1.0}
        sanitised, diffs = sanitise_all_fields(data)
        assert sanitised["proposed_title"] == "cafe"
        assert sanitised["proposed_author"] == "naive"
        assert sanitised["proposed_series_index"] == 1.0
        assert "proposed_title" in diffs
        assert "proposed_author" in diffs

    def test_no_diffs_for_ascii(self):
        data = {"proposed_title": "Hello", "proposed_author": "World"}
        sanitised, diffs = sanitise_all_fields(data)
        assert sanitised["proposed_title"] == "Hello"
        assert len(diffs) == 0

    def test_non_string_fields_untouched(self):
        data = {"proposed_year": 2020, "proposed_series_index": 3.0}
        sanitised, diffs = sanitise_all_fields(data)
        assert sanitised["proposed_year"] == 2020
        assert sanitised["proposed_series_index"] == 3.0
