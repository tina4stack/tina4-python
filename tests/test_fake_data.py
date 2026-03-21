# Tests for tina4_python.seeder.FakeData (v3)
import re
import pytest
from tina4_python.seeder import FakeData


class TestFakeDataBasic:

    def test_name_returns_string(self):
        fake = FakeData()
        name = fake.name()
        assert isinstance(name, str)
        assert " " in name

    def test_first_name_returns_string(self):
        fake = FakeData()
        assert isinstance(fake.first_name(), str)
        assert len(fake.first_name()) > 0

    def test_last_name_returns_string(self):
        fake = FakeData()
        assert isinstance(fake.last_name(), str)
        assert len(fake.last_name()) > 0

    def test_email_has_at_sign(self):
        fake = FakeData()
        email = fake.email()
        assert "@" in email
        assert "." in email.split("@")[1]

    def test_phone_has_digits(self):
        fake = FakeData()
        phone = fake.phone()
        digits = re.sub(r"\D", "", phone)
        assert len(digits) >= 10


class TestFakeDataNumbers:

    def test_integer_within_range(self):
        fake = FakeData(seed=42)
        for _ in range(20):
            val = fake.integer(10, 50)
            assert 10 <= val <= 50

    def test_integer_default_range(self):
        fake = FakeData()
        val = fake.integer()
        assert 0 <= val <= 10000

    def test_decimal_within_range(self):
        fake = FakeData(seed=42)
        for _ in range(20):
            val = fake.decimal(1.0, 10.0, 2)
            assert 1.0 <= val <= 10.0

    def test_decimal_respects_precision(self):
        fake = FakeData(seed=42)
        val = fake.decimal(0.0, 100.0, 3)
        # Check no more than 3 decimal places
        as_str = f"{val:.10f}".rstrip("0")
        if "." in as_str:
            assert len(as_str.split(".")[1]) <= 3

    def test_boolean_returns_bool(self):
        fake = FakeData()
        assert isinstance(fake.boolean(), bool)


class TestFakeDataText:

    def test_word_returns_string(self):
        fake = FakeData()
        assert isinstance(fake.word(), str)
        assert len(fake.word()) > 0

    def test_sentence_ends_with_period(self):
        fake = FakeData()
        s = fake.sentence()
        assert s.endswith(".")

    def test_sentence_word_count(self):
        fake = FakeData(seed=42)
        s = fake.sentence(words=5)
        # Ends with period; remove it then count words
        word_count = len(s.rstrip(".").split())
        assert word_count == 5

    def test_sentence_starts_uppercase(self):
        fake = FakeData(seed=42)
        s = fake.sentence()
        assert s[0].isupper()

    def test_paragraph_contains_multiple_sentences(self):
        fake = FakeData()
        p = fake.paragraph(sentences=3)
        # Should have at least 3 periods
        assert p.count(".") >= 3

    def test_text_contains_multiple_paragraphs(self):
        fake = FakeData()
        t = fake.text(paragraphs=2)
        assert "\n\n" in t


class TestFakeDataDates:

    def test_date_format(self):
        fake = FakeData(seed=42)
        d = fake.date()
        assert re.match(r"\d{4}-\d{2}-\d{2}", d)

    def test_date_within_range(self):
        fake = FakeData(seed=42)
        d = fake.date(start_year=2023, end_year=2024)
        year = int(d.split("-")[0])
        assert 2023 <= year <= 2024

    def test_datetime_iso_format(self):
        fake = FakeData(seed=42)
        dt = fake.datetime_iso()
        assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", dt)


class TestFakeDataMisc:

    def test_uuid_format(self):
        fake = FakeData(seed=42)
        u = fake.uuid()
        assert re.match(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", u)

    def test_url_starts_with_https(self):
        fake = FakeData()
        assert fake.url().startswith("https://")

    def test_address_contains_city(self):
        fake = FakeData(seed=42)
        addr = fake.address()
        assert "," in addr

    def test_color_hex_format(self):
        fake = FakeData(seed=42)
        c = fake.color_hex()
        assert re.match(r"#[0-9a-f]{6}", c)

    def test_alphanumeric_length(self):
        fake = FakeData()
        s = fake.alphanumeric(20)
        assert len(s) == 20
        assert s.isalnum()

    def test_choice_from_list(self):
        fake = FakeData(seed=42)
        items = ["a", "b", "c"]
        assert fake.choice(items) in items

    def test_sample_respects_k(self):
        fake = FakeData(seed=42)
        items = [1, 2, 3, 4, 5]
        result = fake.sample(items, 3)
        assert len(result) == 3
        assert all(x in items for x in result)

    def test_sample_k_larger_than_list(self):
        fake = FakeData(seed=42)
        items = [1, 2]
        result = fake.sample(items, 5)
        assert len(result) == 2


class TestDeterministicSeed:

    def test_same_seed_same_output(self):
        a = FakeData(seed=123)
        b = FakeData(seed=123)
        assert a.name() == b.name()
        assert a.email() == b.email()
        assert a.integer() == b.integer()

    def test_different_seed_different_output(self):
        a = FakeData(seed=1)
        b = FakeData(seed=2)
        # Very unlikely to match with different seeds
        assert a.name() != b.name() or a.email() != b.email()

    def test_seed_factory_method(self):
        fake = FakeData.seed(42)
        assert isinstance(fake, FakeData)
        assert fake.name()  # Should work normally
