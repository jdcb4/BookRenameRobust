"""Tests for subtitle stripping — generic phrases and meaningful preservation."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.sanitiser import strip_generic_subtitle


class TestStripGenericSubtitle:
    def test_strip_a_novel(self):
        assert strip_generic_subtitle("The Hunger Games: A Novel") == "The Hunger Games"

    def test_strip_a_thriller(self):
        assert strip_generic_subtitle("Gone Girl: A Thriller") == "Gone Girl"

    def test_strip_a_mystery(self):
        assert strip_generic_subtitle("The Da Vinci Code: A Mystery") == "The Da Vinci Code"

    def test_strip_a_memoir(self):
        assert strip_generic_subtitle("Educated: A Memoir") == "Educated"

    def test_strip_a_true_story(self):
        assert strip_generic_subtitle("Wild: A True Story") == "Wild"

    def test_strip_book_one(self):
        assert strip_generic_subtitle("Divergent: Book One") == "Divergent"

    def test_strip_book_1(self):
        assert strip_generic_subtitle("Divergent: Book 1") == "Divergent"

    def test_strip_part_one(self):
        assert strip_generic_subtitle("The Stand: Part One") == "The Stand"

    def test_strip_part_1(self):
        assert strip_generic_subtitle("The Stand: Part 1") == "The Stand"

    def test_strip_a_romance(self):
        assert strip_generic_subtitle("The Notebook: A Romance") == "The Notebook"

    def test_strip_an_epic_fantasy(self):
        assert strip_generic_subtitle("The Name of the Wind: An Epic Fantasy") == "The Name of the Wind"

    def test_strip_the_novel(self):
        assert strip_generic_subtitle("It: The Novel") == "It"

    def test_strip_a_story(self):
        assert strip_generic_subtitle("The Gift: A Story") == "The Gift"

    def test_strip_a_legal_thriller(self):
        assert strip_generic_subtitle("The Firm: A Legal Thriller") == "The Firm"

    def test_strip_with_dash_separator(self):
        assert strip_generic_subtitle("The Hunger Games - A Novel") == "The Hunger Games"

    def test_case_insensitive(self):
        assert strip_generic_subtitle("Title: a novel") == "Title"

    def test_preserve_meaningful_subtitle(self):
        result = strip_generic_subtitle("The Lord of the Rings: The Fellowship of the Ring")
        assert result == "The Lord of the Rings: The Fellowship of the Ring"

    def test_preserve_informative_subtitle(self):
        result = strip_generic_subtitle("Sapiens: A Brief History of Humankind")
        assert result == "Sapiens: A Brief History of Humankind"

    def test_no_subtitle_unchanged(self):
        assert strip_generic_subtitle("1984") == "1984"

    def test_empty_string(self):
        assert strip_generic_subtitle("") == ""

    def test_strip_short_story_collection(self):
        assert strip_generic_subtitle("Stories: A Short Story Collection") == "Stories"

    def test_strip_trailing_whitespace(self):
        assert strip_generic_subtitle("Title: A Novel ") == "Title"

    def test_multiple_colons_only_strip_generic(self):
        result = strip_generic_subtitle("Title: Subtitle: A Novel")
        assert result == "Title: Subtitle"
