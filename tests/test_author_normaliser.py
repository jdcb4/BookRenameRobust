"""Tests for author normalisation — Last, First formatting and edge cases."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.sanitiser import normalise_author


class TestNormaliseAuthor:
    def test_first_last_to_last_first(self):
        assert normalise_author("Stephen King") == "King, Stephen"

    def test_already_last_first(self):
        assert normalise_author("King, Stephen") == "King, Stephen"

    def test_middle_name(self):
        assert normalise_author("J.R.R. Tolkien") == "Tolkien, J.R.R."

    def test_two_part_first_name(self):
        assert normalise_author("Ursula K. Le Guin") == "Guin, Ursula K. Le"

    def test_strip_co_authors_semicolon(self):
        assert normalise_author("Stephen King; Peter Straub") == "King, Stephen"

    def test_strip_co_authors_and(self):
        assert normalise_author("Stephen King and Peter Straub") == "King, Stephen"

    def test_strip_co_authors_ampersand(self):
        assert normalise_author("Stephen King & Peter Straub") == "King, Stephen"

    def test_strip_with_keyword(self):
        assert normalise_author("Stephen King with Peter Straub") == "King, Stephen"

    def test_strip_et_al(self):
        assert normalise_author("Stephen King et al.") == "King, Stephen"

    def test_strip_by_prefix(self):
        assert normalise_author("by Stephen King") == "King, Stephen"

    def test_strip_written_by_prefix(self):
        assert normalise_author("Written by Stephen King") == "King, Stephen"

    def test_single_name(self):
        assert normalise_author("Plato") == "Plato"

    def test_empty_string(self):
        assert normalise_author("") == ""

    def test_strip_editor_role(self):
        assert normalise_author("Stephen King (Editor)") == "King, Stephen"

    def test_strip_translator_role(self):
        assert normalise_author("Gabriel Garcia Marquez (Translator: Gregory Rabassa)") == "Marquez, Gabriel Garcia"

    def test_initials(self):
        assert normalise_author("J.K. Rowling") == "Rowling, J.K."

    def test_last_first_with_extra_spaces(self):
        assert normalise_author("  King ,  Stephen  ") == "King, Stephen"
