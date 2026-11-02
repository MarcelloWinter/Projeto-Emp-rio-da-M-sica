"""Deterministic tests for the data layer (no network, no LLM)."""
from datetime import datetime

import pytest

from emporio_agent.config import TIMEZONE
from emporio_agent.data.catalog import Catalog, brl, max_interest_free_installments
from emporio_agent.store_hours import store_status


@pytest.fixture(scope="module")
def catalog():
    return Catalog()


def test_brl_format():
    assert brl(1299) == "R$ 1.299,00"
    assert brl(429.9) == "R$ 429,90"


@pytest.mark.parametrize("price,expected", [(429.9, 5), (599.9, 6), (699.9, 6), (799.9, 7), (2199, 12), (159.9, 3), (40, 1)])
def test_installment_rules(price, expected):
    assert max_interest_free_installments(price) == expected


def test_search_by_category_and_price(catalog):
    res = catalog.search_products(category="Violões", max_price=1000, in_stock_only=True)
    assert res["total_matches"] > 0
    assert all(p["list_price"] <= 1000 and p["available_for_purchase"] for p in res["products"])
    assert all(p["category"] == "Violões" for p in res["products"])


def test_plural_and_accent_insensitive_query(catalog):
    assert catalog.search_products(query="violoes")["total_matches"] == catalog.search_products(query="violões")["total_matches"] > 0


def test_unknown_category_returns_categories(catalog):
    res = catalog.search_products(category="Pedais")
    assert "error" in res and res["categories"]


def test_get_product_by_name_and_pix_price(catalog):
    p = catalog.get_product(name="takamine gd20")
    assert p["product_id"] == 95 and p["promotion"] is None
    assert p["pix_price_text"] == "R$ 2.089,05"


def test_active_promotion_blocks_pix_and_applies_discount(catalog):
    p = catalog.get_product(product_id=121)  # Ohana CK-20, active 20% promo
    assert p["promotion"]["discount_percent"] == 20
    assert p["current_price"] == pytest.approx(549 * 0.8)
    assert "pix_price_text" not in p


def test_inactive_promotion_ignored(catalog):
    assert catalog.get_product(product_id=93)["promotion"] is None  # only inactive promos


def test_out_of_stock_product_gets_alternatives_and_no_pix(catalog):
    p = catalog.get_product(product_id=96)  # stock 0
    assert not p["available_for_purchase"]
    assert "pix_price_text" not in p
    assert p["suggested_alternatives"] and all(a["available_for_purchase"] for a in p["suggested_alternatives"])


def test_discontinued_and_coming_soon_not_available(catalog):
    assert not catalog.get_product(product_id=113)["available_for_purchase"]
    assert not catalog.get_product(product_id=130)["available_for_purchase"]


def test_typo_tolerant_name_lookup(catalog):
    res = catalog.get_product(name="shelby sn7c")
    assert res["candidates"][0]["product_id"] == 113


def test_order_requires_matching_identity(catalog):
    assert "error" in catalog.get_order(1, "someone@else.com")
    assert "error" in catalog.get_order(1, "")
    assert "error" in catalog.get_order(9999, "pedro.oliveira@jmail.com")
    ok = catalog.get_order(1, "PEDRO.OLIVEIRA@jmail.com")
    assert ok["status_code"] == "delivered" and ok["customer_first_name"] == "Pedro"


def test_order_lookup_by_phone_ignores_formatting(catalog):
    assert catalog.get_order(1, "67 98432 1098")["order_id"] == 1


def test_cancelled_order_exposes_reason_and_no_tracking(catalog):
    o = catalog.get_order(20, "(67) 98321-6543")  # customer 7
    assert o["status_code"] == "cancelled" and "Endereço" in o["notes"] and o["tracking_code"] is None


def test_find_customer_orders(catalog):
    res = catalog.find_customer_orders("thiago.barbosa@jmail.com")
    assert {o["order_id"] for o in res["orders"]} == {2, 20}
    assert "error" in catalog.find_customer_orders("nobody@nowhere.com")


def test_store_status_open_and_closed():
    mon = store_status(datetime(2026, 3, 23, 10, 30, tzinfo=TIMEZONE))
    assert mon["is_open"]
    sat_late = store_status(datetime(2026, 3, 28, 14, 0, tzinfo=TIMEZONE))
    assert not sat_late["is_open"] and "segunda-feira" in sat_late["next_opening"]
    sun = store_status(datetime(2026, 3, 29, 11, 0, tzinfo=TIMEZONE))
    assert not sun["is_open"]


def test_shared_email_is_not_resolved_to_a_single_customer(catalog):
    assert "error" in catalog.find_customer_orders("bruno.martins@jmail.com")
    assert catalog.get_order(10, "bruno.martins@jmail.com")["order_id"] == 10  # customer 11 still verifies per order
