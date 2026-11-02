"""Load and clean the CSV tables once, as typed pandas DataFrames."""
import json
import re
from dataclasses import dataclass
from functools import lru_cache

import pandas as pd

from ..config import DATA_DIR


@dataclass(frozen=True)
class Data:
    categories: pd.DataFrame
    customers: pd.DataFrame
    products: pd.DataFrame
    promotions: pd.DataFrame
    orders: pd.DataFrame
    order_items: pd.DataFrame


def _read(name: str) -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / f"{name}.csv", encoding="utf-8")


def _parse_specs(raw) -> dict:
    try:
        return json.loads(raw) if isinstance(raw, str) else {}
    except json.JSONDecodeError:
        return {}


@lru_cache(maxsize=1)
def load_data() -> Data:
    categories = _read("categories")
    categories["name"] = categories["name"].str.strip()

    customers = _read("customers")
    customers["email"] = customers["email"].str.strip().str.lower()
    customers["phone_digits"] = customers["phone"].astype(str).map(lambda p: re.sub(r"\D", "", p))

    products = _read("products")
    products["name"] = products["name"].str.strip()
    products["status"] = products["status"].str.strip().str.lower()
    products["specs"] = products["specs"].map(_parse_specs)
    products["stock_quantity"] = products["stock_quantity"].fillna(0).astype(int)
    products = products.merge(
        categories[["category_id", "name"]].rename(columns={"name": "category_name"}),
        on="category_id", how="left",
    )

    promotions = _read("promotions")
    promotions["is_active"] = promotions["is_active"].astype(int).astype(bool)

    orders = _read("orders")
    orders["order_date"] = pd.to_datetime(orders["order_date"]).dt.date
    orders["estimated_delivery"] = pd.to_datetime(orders["estimated_delivery"]).dt.date
    orders["status"] = orders["status"].str.strip().str.lower()

    order_items = _read("order_items")

    return Data(categories, customers, products, promotions, orders, order_items)
