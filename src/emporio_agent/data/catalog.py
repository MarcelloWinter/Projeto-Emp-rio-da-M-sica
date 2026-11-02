"""Typed, deterministic queries over the CSV data.

All prices, discounts and installment limits are computed here so the LLM never
does arithmetic on money.
"""
import re
import unicodedata
from datetime import date

from rapidfuzz import fuzz

from ..config import now
from .loader import Data, load_data

PIX_DISCOUNT = 0.05
STATUS_PT = {
    "pending": "pendente (aguardando processamento)",
    "confirmed": "confirmado",
    "shipped": "enviado",
    "delivered": "entregue",
    "cancelled": "cancelado",
}
PRODUCT_STATUS_PT = {
    "active": "ativo",
    "discontinued": "descontinuado (fora do catálogo)",
    "coming_soon": "em breve (ainda não disponível para venda)",
}
STOPWORDS = {"de", "da", "do", "das", "dos", "para", "com", "um", "uma", "o", "a", "e", "em",
             "ate", "que", "quais", "qual", "quero", "tem", "voces", "opcoes", "disponiveis"}


def brl(value: float) -> str:
    return "R$ " + f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def _stem(token: str) -> str:
    if token.endswith("oes"):
        return token[:-3] + "ao"
    if token.endswith("s") and len(token) > 3:
        return token[:-1]
    return token


def _tokens(text: str) -> set[str]:
    return {_stem(t) for t in re.findall(r"[a-z0-9]+", norm(text)) if t not in STOPWORDS}


def max_interest_free_installments(price: float) -> int:
    """Manual 3.1: <=3x min R$50/parcel, 4-6x min R$80, 7-12x min R$100."""
    for n in range(12, 0, -1):
        minimum = 100 if n >= 7 else 80 if n >= 4 else 50
        if price / n >= minimum:
            return n
    return 1


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", norm(text))


def _fuzzy(query: str, name: str) -> float:
    """Typo/hyphen tolerant similarity ("sn7c" ~ "SN-7C")."""
    q, n = _squash(query), _squash(name)
    partial = fuzz.partial_ratio(q, n) if len(q) >= 4 else 0
    return max(fuzz.WRatio(norm(query), norm(name)), partial)


def _digits(text: str) -> str:
    return re.sub(r"\D", "", str(text))


class Catalog:
    def __init__(self, data: Data | None = None):
        self.d = data or load_data()

    # ------------------------------------------------------------------ products
    def _active_discount(self, product_id: int) -> dict | None:
        promos = self.d.promotions
        rows = promos[(promos.product_id == product_id) & promos.is_active]
        if rows.empty:
            return None
        best = rows.sort_values("discount_percent", ascending=False).iloc[0]
        return {"discount_percent": int(best.discount_percent), "label": str(best.description)}

    def _view(self, row, detailed: bool = False) -> dict:
        price = float(row.price_brl)
        promo = self._active_discount(int(row.product_id))
        final = round(price * (1 - promo["discount_percent"] / 100), 2) if promo else price
        sellable = row.status == "active" and row.stock_quantity > 0
        view = {
            "product_id": int(row.product_id),
            "name": row.name,
            "category": row.category_name,
            "status": PRODUCT_STATUS_PT.get(row.status, row.status),
            "stock_quantity": int(row.stock_quantity),
            "available_for_purchase": sellable,
            "list_price": price,
            "list_price_text": brl(price),
        }
        if promo:
            view["promotion"] = {
                **promo,
                "price_from": brl(price),
                "price_to": brl(final),
                "note": "Promoção ativa. O desconto de PIX (5%) NÃO se aplica a preço promocional.",
            }
            view["current_price"], view["current_price_text"] = final, brl(final)
        else:
            view["promotion"] = None
            view["current_price"], view["current_price_text"] = price, brl(price)
            if sellable:
                view["pix_price_text"] = brl(round(price * (1 - PIX_DISCOUNT), 2))
        if sellable:
            view["max_interest_free_installments"] = max_interest_free_installments(final)
        if detailed:
            view["description"] = row.description
            view["specs"] = row.specs
        return view

    def _alternatives(self, row, limit: int = 3) -> list[dict]:
        """Available products of the same category with a similar price (manual 7.3)."""
        df = self.d.products
        df = df[(df.category_id == row.category_id) & (df.product_id != row.product_id)
                & (df.status == "active") & (df.stock_quantity > 0)]
        df = df.assign(_gap=(df.price_brl - row.price_brl).abs()).sort_values("_gap")
        return [self._view(r) for r in df.head(limit).itertuples()]

    def _detailed(self, row) -> dict:
        view = self._view(row, detailed=True)
        if not view["available_for_purchase"]:
            view["suggested_alternatives"] = self._alternatives(row)
        return view

    def _category_ids(self, category: str | None) -> list[int] | None:
        if not category:
            return None
        wanted = _tokens(category)
        cats = self.d.categories
        hits = [int(r.category_id) for r in cats.itertuples() if wanted and wanted <= _tokens(r.name)]
        if not hits:
            scored = [(fuzz.WRatio(norm(category), norm(r.name)), int(r.category_id)) for r in cats.itertuples()]
            best = max(scored)
            hits = [best[1]] if best[0] >= 75 else []
        return hits

    def search_products(self, query: str | None = None, category: str | None = None,
                        min_price: float | None = None, max_price: float | None = None,
                        in_stock_only: bool = False, limit: int = 10) -> dict:
        df = self.d.products
        cat_ids = self._category_ids(category)
        if category and not cat_ids:
            return {"error": f"Categoria '{category}' não encontrada.",
                    "categories": self.list_categories()["categories"]}
        if cat_ids:
            df = df[df.category_id.isin(cat_ids)]
        if min_price is not None:
            df = df[df.price_brl >= min_price]
        if max_price is not None:
            df = df[df.price_brl <= max_price]
        if in_stock_only:
            df = df[(df.status == "active") & (df.stock_quantity > 0)]

        if query and (qt := _tokens(query)):
            def spec_text(r):
                return " ".join(map(str, r.specs.values()))

            core = df[df.apply(lambda r: qt <= _tokens(f"{r['name']} {r.category_name} {spec_text(r)}"), axis=1)]
            if core.empty:
                core = df[df.apply(lambda r: qt <= _tokens(f"{r['name']} {r.category_name} {r.description}"), axis=1)]
            df = core

        df = df.assign(_avail=((df.status == "active") & (df.stock_quantity > 0)).astype(int))
        df = df.sort_values(["_avail", "price_brl"], ascending=[False, True])
        total = len(df)
        items = [self._view(r) for r in df.head(limit).itertuples()]
        return {"total_matches": total, "returned": len(items), "products": items}

    def get_product(self, product_id: int | None = None, name: str | None = None) -> dict:
        df = self.d.products
        if product_id is not None:
            rows = df[df.product_id == int(product_id)]
            if rows.empty:
                return {"error": f"Produto {product_id} não encontrado."}
            return self._detailed(next(rows.itertuples()))
        if not name:
            return {"error": "Informe product_id ou name."}
        qt = _tokens(name)
        hits = df[df["name"].map(lambda n: qt <= _tokens(n))] if qt else df.iloc[0:0]
        if len(hits) == 1:
            return self._detailed(next(hits.itertuples()))
        if len(hits) > 1:
            return {"ambiguous": True, "candidates": [self._view(r) for r in hits.head(5).itertuples()],
                    "note": "Vários produtos correspondem; pergunte ao cliente qual deles."}
        scored = df.assign(_s=df["name"].map(lambda n: _fuzzy(name, n)))
        top = scored[scored._s >= 75].sort_values("_s", ascending=False).head(3)
        if top.empty:
            return {"error": f"Nenhum produto encontrado para '{name}'. Não fazemos acessórios, apenas instrumentos."}
        return {"ambiguous": True, "note": "Nome não encontrado exatamente; possíveis correspondências.",
                "candidates": [self._view(r) for r in top.itertuples()]}

    def list_categories(self) -> dict:
        counts = self.d.products.groupby("category_id").size()
        return {"categories": [
            {"category_id": int(r.category_id), "name": r.name, "description": r.description,
             "products_in_catalog": int(counts.get(r.category_id, 0))}
            for r in self.d.categories.itertuples()]}

    def get_active_promotions(self, category: str | None = None) -> dict:
        promos = self.d.promotions[self.d.promotions.is_active]
        cat_ids = self._category_ids(category)
        out = []
        for p in promos.itertuples():
            rows = self.d.products[self.d.products.product_id == p.product_id]
            if rows.empty:
                continue
            row = next(rows.itertuples())
            if cat_ids and row.category_id not in cat_ids:
                continue
            out.append(self._view(row))
        out.sort(key=lambda v: -v["promotion"]["discount_percent"])
        return {"active_promotions": out, "count": len(out)}

    # -------------------------------------------------------------------- orders
    def _verify(self, customer_id: int, proof: str) -> bool:
        c = self.d.customers[self.d.customers.customer_id == customer_id]
        if c.empty or not proof or not proof.strip():
            return False
        row = next(c.itertuples())
        proof = proof.strip()
        if "@" in proof:
            return proof.lower() == row.email
        digits = _digits(proof)
        return len(digits) >= 8 and digits[-9:] == row.phone_digits[-9:]

    def _order_view(self, o, customer) -> dict:
        items = self.d.order_items[self.d.order_items.order_id == o.order_id]
        lines = []
        for it in items.itertuples():
            p = self.d.products[self.d.products.product_id == it.product_id]
            lines.append({"product": p.iloc[0]["name"] if not p.empty else f"produto #{it.product_id}",
                          "quantity": int(it.quantity)})
        est = o.estimated_delivery if isinstance(o.estimated_delivery, date) else None
        view = {
            "order_id": int(o.order_id),
            "customer_first_name": customer.name.split()[0],
            "placed_on": o.order_date.isoformat(),
            "status": STATUS_PT.get(o.status, o.status),
            "status_code": o.status,
            "total": brl(float(o.total_brl)),
            "payment_method": o.payment_method,
            "items": lines,
            "tracking_code": o.tracking_code if isinstance(o.tracking_code, str) else None,
            "forecast_delivery_date": est.isoformat() if est else None,
            "notes": o.notes if isinstance(o.notes, str) else None,
        }
        if o.status == "delivered" and est:
            days = (now().date() - est).days
            view["return_windows"] = {
                "basis": "Data de entrega PREVISTA (a data real de recebimento não é registrada).",
                "days_since_estimated_delivery": days,
                "within_7_day_regret_window": days <= 7,
                "within_30_day_defect_exchange_window": days <= 30,
                "within_90_day_legal_warranty": days <= 90,
            }
        return view

    def get_order(self, order_id: int, email_or_phone: str) -> dict:
        o = self.d.orders[self.d.orders.order_id == int(order_id)]
        deny = {"error": "Não foi possível validar o pedido. Confirme o número do pedido e o e-mail ou telefone cadastrado."}
        if o.empty:
            return deny
        order = next(o.itertuples())
        if not self._verify(int(order.customer_id), email_or_phone):
            return deny
        customer = next(self.d.customers[self.d.customers.customer_id == order.customer_id].itertuples())
        return self._order_view(order, customer)

    def find_customer_orders(self, email_or_phone: str) -> dict:
        proof = (email_or_phone or "").strip()
        matches = [c for c in self.d.customers.itertuples() if self._verify(int(c.customer_id), proof)]
        if not matches:
            return {"error": "Nenhum cliente encontrado com esse e-mail/telefone."}
        c = matches[0]
        orders = self.d.orders[self.d.orders.customer_id == c.customer_id].sort_values("order_date")
        return {"customer_first_name": c.name.split()[0],
                "orders": [self._order_view(o, c) for o in orders.itertuples()]}
