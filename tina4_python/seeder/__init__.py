# Tina4 Seeder — Fake data generation and database seeding, zero dependencies.
"""
Generate realistic fake data for testing and development.

    from tina4_python.seeder import Fake, seed_table

    fake = Fake()
    fake.name()      # "Alice Johnson"
    fake.email()     # "alice.johnson@example.com"

    seed_table(db, "users", 50, {"name": fake.name, "email": fake.email})
"""
import random
import string
import hashlib
from datetime import datetime, timedelta, timezone

# Word banks for generating realistic data
_FIRST_NAMES = [
    "Alice", "Bob", "Charlie", "Diana", "Eve", "Frank", "Grace", "Henry",
    "Ivy", "Jack", "Kate", "Leo", "Mia", "Noah", "Olivia", "Pete",
    "Quinn", "Rose", "Sam", "Tina", "Uma", "Vince", "Wendy", "Xander",
    "Yara", "Zane", "Anna", "Ben", "Chloe", "Dan", "Emma", "Felix",
]
_LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Wilson",
    "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee",
    "Perez", "Thompson", "White", "Harris", "Clark", "Lewis", "Young",
]
_DOMAINS = ["example.com", "test.org", "demo.net", "mail.dev", "inbox.io"]
_WORDS = [
    "the", "quick", "brown", "fox", "jumps", "over", "lazy", "dog",
    "lorem", "ipsum", "dolor", "sit", "amet", "consectetur", "adipiscing",
    "elit", "sed", "do", "eiusmod", "tempor", "incididunt", "ut", "labore",
    "magna", "aliqua", "enim", "minim", "veniam", "quis", "nostrud",
    "exercitation", "ullamco", "laboris", "nisi", "aliquip", "commodo",
]
_CITIES = [
    "New York", "London", "Tokyo", "Paris", "Sydney", "Berlin", "Toronto",
    "Cape Town", "Mumbai", "Singapore", "Dubai", "Amsterdam", "Seoul",
]
_STREETS = [
    "Main St", "Oak Ave", "Park Rd", "Cedar Ln", "Elm St", "Pine Dr",
    "Maple Way", "River Rd", "Lake Blvd", "Hill Ct", "Valley View",
]


class Fake:
    """Fake data generator with deterministic seeding."""

    def __init__(self, seed: int = None):
        self._rng = random.Random(seed)

    def name(self) -> str:
        return f"{self._rng.choice(_FIRST_NAMES)} {self._rng.choice(_LAST_NAMES)}"

    def first_name(self) -> str:
        return self._rng.choice(_FIRST_NAMES)

    def last_name(self) -> str:
        return self._rng.choice(_LAST_NAMES)

    def email(self) -> str:
        first = self._rng.choice(_FIRST_NAMES).lower()
        last = self._rng.choice(_LAST_NAMES).lower()
        domain = self._rng.choice(_DOMAINS)
        return f"{first}.{last}@{domain}"

    def phone(self) -> str:
        area = self._rng.randint(200, 999)
        mid = self._rng.randint(100, 999)
        end = self._rng.randint(1000, 9999)
        return f"+1 ({area}) {mid}-{end}"

    def integer(self, min_val: int = 0, max_val: int = 10000) -> int:
        return self._rng.randint(min_val, max_val)

    def decimal(self, min_val: float = 0.0, max_val: float = 1000.0, decimals: int = 2) -> float:
        return round(self._rng.uniform(min_val, max_val), decimals)

    def boolean(self) -> bool:
        return self._rng.choice([True, False])

    def word(self) -> str:
        return self._rng.choice(_WORDS)

    def sentence(self, words: int = 8) -> str:
        s = " ".join(self._rng.choice(_WORDS) for _ in range(words))
        return s.capitalize() + "."

    def paragraph(self, sentences: int = 4) -> str:
        return " ".join(self.sentence(self._rng.randint(5, 12)) for _ in range(sentences))

    def text(self, paragraphs: int = 3) -> str:
        return "\n\n".join(self.paragraph() for _ in range(paragraphs))

    def date(self, start_year: int = 2020, end_year: int = 2025) -> str:
        start = datetime(start_year, 1, 1, tzinfo=timezone.utc)
        end = datetime(end_year, 12, 31, tzinfo=timezone.utc)
        delta = (end - start).days
        d = start + timedelta(days=self._rng.randint(0, delta))
        return d.strftime("%Y-%m-%d")

    def datetime_iso(self) -> str:
        d = self.date()
        h = self._rng.randint(0, 23)
        m = self._rng.randint(0, 59)
        s = self._rng.randint(0, 59)
        return f"{d}T{h:02d}:{m:02d}:{s:02d}Z"

    def uuid(self) -> str:
        hex_str = hashlib.md5(
            str(self._rng.random()).encode()
        ).hexdigest()
        return f"{hex_str[:8]}-{hex_str[8:12]}-{hex_str[12:16]}-{hex_str[16:20]}-{hex_str[20:]}"

    def url(self) -> str:
        domain = self._rng.choice(_DOMAINS)
        path = "/".join(self._rng.choice(_WORDS) for _ in range(2))
        return f"https://{domain}/{path}"

    def address(self) -> str:
        num = self._rng.randint(1, 999)
        street = self._rng.choice(_STREETS)
        city = self._rng.choice(_CITIES)
        return f"{num} {street}, {city}"

    def color_hex(self) -> str:
        return f"#{self._rng.randint(0, 0xFFFFFF):06x}"

    def choice(self, items: list):
        return self._rng.choice(items)

    def sample(self, items: list, k: int) -> list:
        return self._rng.sample(items, min(k, len(items)))

    def alphanumeric(self, length: int = 10) -> str:
        chars = string.ascii_letters + string.digits
        return "".join(self._rng.choice(chars) for _ in range(length))


def seed_table(db, table: str, count: int = 10,
               field_map: dict[str, callable] = None,
               overrides: dict = None) -> int:
    """Seed a database table with fake data.

    Args:
        db: Database instance
        table: Table name
        count: Number of rows to insert
        field_map: Dict of column_name → callable that generates a value
        overrides: Static values to set on every row

    Returns:
        Number of rows inserted
    """
    if not field_map:
        return 0

    for i in range(count):
        row = {}
        for col, generator in field_map.items():
            row[col] = generator() if callable(generator) else generator
        if overrides:
            row.update(overrides)
        db.insert(table, row)

    db.commit()
    return count


__all__ = ["Fake", "seed_table"]
