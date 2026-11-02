import csv
from decimal import Decimal
from pathlib import Path

from amiguprecio.references import load_saved_references

DATASET = Path(__file__).parents[1] / "data" / "amigurumis_referencias.csv"


def read_rows() -> list[dict[str, str]]:
    with DATASET.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def test_dataset_contains_verified_finished_products_including_eur() -> None:
    rows = read_rows()

    assert len(rows) == 17
    assert len({row["store"] for row in rows}) >= 3
    assert all(Decimal(row["price"]) > 0 for row in rows)
    assert all(len(row["currency"]) == 3 for row in rows)
    assert all(row["url"].startswith("https://") for row in rows)
    assert all(row["checked_at"] for row in rows)
    assert all(row["product_type"] == "finished_product" for row in rows)
    assert len([row for row in rows if row["currency"] == "EUR"]) == 5


def test_dataset_excludes_patterns_kits_and_ambiguous_prices() -> None:
    rows = read_rows()
    banned = ("pattern", "patrón", "kit", "from ", "desde ")

    for row in rows:
        searchable = " ".join(row.values()).casefold()
        assert not any(term in searchable for term in banned)
        assert "-" not in row["price"]


def test_missing_sizes_remain_empty_and_known_sizes_are_preserved() -> None:
    rows = read_rows()

    assert any(not row["size"] for row in rows)
    assert {"20 cm", "25 cm", "28 cm"}.issubset(
        {row["size"] for row in rows if row["size"]}
    )


def test_mcp_fallback_loader_queries_csv_without_claiming_live_access() -> None:
    references = load_saved_references("turtle")

    assert len(references) == 1
    assert references[0].provenance == "saved"
    assert references[0].title == "Handmade Crochet Turtle Plushie"
