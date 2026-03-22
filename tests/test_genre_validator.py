"""Tests for genre taxonomy validation."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.genre import validate_genre, GENRE_TAXONOMY, ALL_GENRES, ALL_SUBGENRES


class TestValidateGenre:
    def test_valid_fiction_pair(self):
        assert validate_genre("Fiction", "Literary Fiction") is True

    def test_valid_scifi_pair(self):
        assert validate_genre("Science Fiction", "Space Opera") is True

    def test_valid_fantasy_pair(self):
        assert validate_genre("Fantasy", "Epic Fantasy") is True

    def test_valid_thriller_pair(self):
        assert validate_genre("Thriller", "Psychological Thriller") is True

    def test_valid_mystery_pair(self):
        assert validate_genre("Mystery", "Detective") is True

    def test_valid_horror_pair(self):
        assert validate_genre("Horror", "Cosmic Horror") is True

    def test_valid_romance_pair(self):
        assert validate_genre("Romance", "Historical Romance") is True

    def test_valid_nonfiction_pair(self):
        assert validate_genre("Non-Fiction", "Essays") is True

    def test_valid_biography_pair(self):
        assert validate_genre("Biography", "Memoir") is True

    def test_valid_history_pair(self):
        assert validate_genre("History", "Military History") is True

    def test_valid_science_pair(self):
        assert validate_genre("Science", "Popular Science") is True

    def test_valid_business_pair(self):
        assert validate_genre("Business", "Management") is True

    def test_valid_selfhelp_pair(self):
        assert validate_genre("Self-Help", "Productivity") is True

    def test_valid_children_pair(self):
        assert validate_genre("Children and Young Adult", "YA Fiction") is True

    def test_valid_graphic_pair(self):
        assert validate_genre("Graphic Novels and Comics", "Manga") is True

    def test_valid_religion_pair(self):
        assert validate_genre("Religion and Spirituality", "Buddhism") is True

    def test_valid_reference_pair(self):
        assert validate_genre("Reference and Education", "Textbook") is True

    def test_invalid_genre(self):
        assert validate_genre("Cooking", "French Cuisine") is False

    def test_invalid_subgenre(self):
        assert validate_genre("Fiction", "Space Opera") is False

    def test_mismatched_pair(self):
        assert validate_genre("Science Fiction", "Detective") is False

    def test_empty_genre(self):
        assert validate_genre("", "Literary Fiction") is False

    def test_empty_subgenre(self):
        assert validate_genre("Fiction", "") is False

    def test_case_sensitive(self):
        assert validate_genre("fiction", "Literary Fiction") is False

    def test_all_genres_populated(self):
        assert len(ALL_GENRES) >= 18

    def test_all_subgenres_populated(self):
        assert len(ALL_SUBGENRES) >= 80

    def test_every_taxonomy_entry_validates(self):
        for genre, subgenres in GENRE_TAXONOMY.items():
            for subgenre in subgenres:
                assert validate_genre(genre, subgenre), f"Failed: {genre} / {subgenre}"
