"""Tool schemas (OpenAI function calling) and the dispatcher that executes them."""
import json
import logging

from .config import LOGS_DIR, now
from .data.catalog import Catalog
from .policies.retriever import PolicyRetriever
from .store_hours import store_status

log = logging.getLogger(__name__)


def _fn(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required or []}}}


TOOL_SCHEMAS = [
    _fn("search_products",
        "Search the instrument catalog by category, price range and/or keywords (brand, model, "
        "type such as 'folk', 'nylon', 'tenor'). Returns current prices (with active promotions), "
        "stock and availability. Use for 'what do you have...', 'options up to R$X', comparisons. "
        "To check ONE specific model use get_product_details instead. "
        "Do NOT use for accessories (strings, cables, picks, pedals, amps, cases): the store does not sell them.",
        {"query": {"type": "string", "description": "Brand/model/type keywords, e.g. 'Yamaha', 'folk aço'. Omit to list by category/price only."},
         "category": {"type": "string", "description": "Category name, e.g. 'Violões', 'Guitarras', 'Ukuleles', 'Baterias e Percussão'."},
         "min_price": {"type": "number"},
         "max_price": {"type": "number", "description": "Maximum price in BRL."},
         "in_stock_only": {"type": "boolean", "description": "Only products that can be bought right now. Use true for customers who want to buy."},
         "limit": {"type": "integer", "description": "Max results (default 10)."}}),
    _fn("get_product_details",
        "Get full details for ONE product (price, promotion, PIX price, installments, stock, status, specs). "
        "Use for 'how much is the X', 'do you have X in stock'. Accepts a product name (partial/typos OK) or id.",
        {"name": {"type": "string"}, "product_id": {"type": "integer"}}),
    _fn("list_categories", "List instrument categories sold by the store and how many products each has.", {}),
    _fn("get_active_promotions",
        "List ONLY currently active promotions with original price, discount % and final price.",
        {"category": {"type": "string", "description": "Optional category filter."}}),
    _fn("get_order_status",
        "Look up one order. REQUIRES the order number AND the e-mail or phone registered on the order "
        "(identity check). Returns status, items, tracking code, estimated delivery, notes and return-window flags.",
        {"order_id": {"type": "integer"},
         "email_or_phone": {"type": "string", "description": "E-mail or phone given by the customer."}},
        ["order_id", "email_or_phone"]),
    _fn("find_customer_orders",
        "List all orders of a customer identified by registered e-mail or phone. Use when the customer "
        "does not know the order number.",
        {"email_or_phone": {"type": "string"}}, ["email_or_phone"]),
    _fn("search_store_policies",
        "Search the store's policy manual: returns, exchanges, warranty, payment methods, installments, shipping "
        "and delivery, promotions rules, store address/contacts, tracking codes, privacy. Use for ANY question "
        "about rules or procedures. Query in Portuguese.",
        {"query": {"type": "string"}}, ["query"]),
    _fn("get_store_status", "Whether the store is open right now and its opening hours / next opening.", {}),
    _fn("register_complaint",
        "Register a customer complaint for human follow-up (return within 24 business hours). "
        "Only call after the customer described the problem and gave a contact (name + phone or e-mail).",
        {"summary": {"type": "string"}, "contact": {"type": "string"}, "order_id": {"type": "integer"}},
        ["summary", "contact"]),
]


class ToolRegistry:
    def __init__(self, catalog: Catalog | None = None, retriever: PolicyRetriever | None = None):
        self.catalog = catalog or Catalog()
        self.retriever = retriever or PolicyRetriever()

    def _register_complaint(self, summary: str, contact: str, order_id: int | None = None) -> dict:
        LOGS_DIR.mkdir(exist_ok=True)
        entry = {"timestamp": now().isoformat(timespec="seconds"), "summary": summary,
                 "contact": contact, "order_id": order_id}
        with open(LOGS_DIR / "complaints.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return {"registered": True, "follow_up": "Um responsável retornará em até 24 horas úteis."}

    def call(self, name: str, arguments: dict) -> str:
        handlers = {
            "search_products": self.catalog.search_products,
            "get_product_details": self.catalog.get_product,
            "list_categories": self.catalog.list_categories,
            "get_active_promotions": self.catalog.get_active_promotions,
            "get_order_status": self.catalog.get_order,
            "find_customer_orders": self.catalog.find_customer_orders,
            "search_store_policies": lambda query: {"results": self.retriever.search(query, k=4)},
            "get_store_status": store_status,
            "register_complaint": self._register_complaint,
        }
        handler = handlers.get(name)
        if handler is None:
            return json.dumps({"error": f"Ferramenta desconhecida: {name}"})
        try:
            return json.dumps(handler(**arguments), ensure_ascii=False, default=str)
        except Exception as exc:  # tool failures are fed back to the model, never crash the chat
            log.exception("Tool %s failed", name)
            return json.dumps({"error": f"Falha ao executar {name}: {exc}"}, ensure_ascii=False)
