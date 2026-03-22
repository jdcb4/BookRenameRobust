"""Genre taxonomy constants and validation."""

GENRE_TAXONOMY: dict[str, list[str]] = {
    "Fiction": [
        "Literary Fiction", "Historical Fiction", "Contemporary Fiction", "Short Stories",
    ],
    "Science Fiction": [
        "Space Opera", "Hard Sci-Fi", "Cyberpunk", "Dystopian", "Military Sci-Fi",
        "Time Travel", "First Contact",
    ],
    "Fantasy": [
        "Epic Fantasy", "Urban Fantasy", "Dark Fantasy", "Grimdark",
        "Sword and Sorcery", "Mythic Fantasy", "Cosy Fantasy",
    ],
    "Thriller": [
        "Psychological Thriller", "Legal Thriller", "Political Thriller",
        "Espionage", "Techno-Thriller", "Medical Thriller",
    ],
    "Mystery": [
        "Detective", "Cosy Mystery", "Noir", "Crime", "Police Procedural",
        "Historical Mystery",
    ],
    "Horror": [
        "Supernatural Horror", "Psychological Horror", "Gothic", "Cosmic Horror",
        "Splatterpunk",
    ],
    "Romance": [
        "Contemporary Romance", "Historical Romance", "Paranormal Romance",
        "Romantic Suspense", "Erotic Romance",
    ],
    "Non-Fiction": [
        "Essays", "Journalism", "Travel Writing", "Nature Writing", "Food Writing",
    ],
    "Biography": [
        "Autobiography", "Memoir", "Biography", "Celebrity Memoir",
    ],
    "History": [
        "Military History", "Political History", "Social History",
        "Ancient History", "Modern History",
    ],
    "Science": [
        "Popular Science", "Physics", "Biology", "Medicine", "Technology",
        "Maths", "Environment",
    ],
    "Politics and Society": [
        "Political Theory", "Sociology", "Economics", "Philosophy", "Law",
        "Current Affairs",
    ],
    "Self-Help": [
        "Personal Development", "Productivity", "Mental Health", "Relationships",
        "Finance", "Health and Fitness",
    ],
    "Business": [
        "Management", "Entrepreneurship", "Marketing", "Leadership", "Strategy",
    ],
    "Children and Young Adult": [
        "Picture Books", "Middle Grade", "YA Fiction", "YA Fantasy", "YA Romance",
    ],
    "Graphic Novels and Comics": [
        "Superhero", "Manga", "Graphic Memoir", "Indie Comics",
    ],
    "Religion and Spirituality": [
        "Christianity", "Islam", "Buddhism", "Spirituality", "New Age",
    ],
    "Reference and Education": [
        "Textbook", "Language Learning", "Study Guide", "Dictionary",
    ],
}

ALL_GENRES: set[str] = set(GENRE_TAXONOMY.keys())
ALL_SUBGENRES: set[str] = {sg for sgs in GENRE_TAXONOMY.values() for sg in sgs}


def validate_genre(genre: str, subgenre: str) -> bool:
    """Return True if the genre/subgenre pair is in the approved taxonomy."""
    if genre not in GENRE_TAXONOMY:
        return False
    return subgenre in GENRE_TAXONOMY[genre]


def genre_taxonomy_for_prompt() -> str:
    """Format the taxonomy as a string for inclusion in LLM prompts."""
    lines = []
    for genre, subgenres in GENRE_TAXONOMY.items():
        lines.append(f"{genre}: {' | '.join(subgenres)}")
    return "\n".join(lines)
