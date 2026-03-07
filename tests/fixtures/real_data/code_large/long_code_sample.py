"""Long-form sample Python source used as a real transfer acceptance target.

This file is intentionally verbose and includes multiple modules-in-one style
sections so transfer validation can cover realistic code layout and content.
"""

from __future__ import annotations

import dataclasses
import hashlib
import itertools
import json
import math
import random
import statistics
import string
import time
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple


@dataclasses.dataclass
class User:
    user_id: int
    name: str
    email: str
    roles: List[str]


@dataclasses.dataclass
class Product:
    sku: str
    title: str
    price_cents: int
    tags: List[str]


@dataclasses.dataclass
class OrderItem:
    sku: str
    qty: int
    unit_price_cents: int


@dataclasses.dataclass
class Order:
    order_id: str
    user_id: int
    items: List[OrderItem]
    created_at: float

    @property
    def subtotal_cents(self) -> int:
        return sum(item.qty * item.unit_price_cents for item in self.items)


def normalize_email(value: str) -> str:
    return value.strip().lower()


def slugify(value: str) -> str:
    chars = []
    for ch in value.lower():
        if ch.isalnum():
            chars.append(ch)
        elif ch in {" ", "-", "_"}:
            chars.append("-")
    slug = "".join(chars)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")


def stable_hash(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def chunks(seq: Sequence[str], size: int) -> Iterator[Sequence[str]]:
    if size <= 0:
        raise ValueError("size must be > 0")
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


class InMemoryStore:
    def __init__(self) -> None:
        self.users: Dict[int, User] = {}
        self.products: Dict[str, Product] = {}
        self.orders: Dict[str, Order] = {}

    def add_user(self, user: User) -> None:
        self.users[user.user_id] = user

    def add_product(self, product: Product) -> None:
        self.products[product.sku] = product

    def add_order(self, order: Order) -> None:
        self.orders[order.order_id] = order

    def user_orders(self, user_id: int) -> List[Order]:
        result = [o for o in self.orders.values() if o.user_id == user_id]
        result.sort(key=lambda o: o.created_at)
        return result


def generate_users(n: int, seed: int = 7) -> List[User]:
    random.seed(seed)
    out = []
    for i in range(1, n + 1):
        name = "User{}".format(i)
        email = normalize_email("{}@example.com".format(name))
        roles = ["member"]
        if i % 10 == 0:
            roles.append("vip")
        out.append(User(user_id=i, name=name, email=email, roles=roles))
    return out


def generate_products(n: int, seed: int = 11) -> List[Product]:
    random.seed(seed)
    out = []
    vocab = ["camera", "lens", "stand", "light", "mic", "screen", "cable"]
    for i in range(n):
        name = "{} {}".format(random.choice(vocab), i)
        sku = "SKU-{:05d}".format(i)
        price = random.randint(999, 99999)
        tags = [slugify(name), random.choice(vocab)]
        out.append(Product(sku=sku, title=name, price_cents=price, tags=tags))
    return out


def generate_orders(
    users: List[User], products: List[Product], n: int, seed: int = 23
) -> List[Order]:
    random.seed(seed)
    out = []
    now = time.time()
    for i in range(n):
        user = random.choice(users)
        k = random.randint(1, 4)
        items: List[OrderItem] = []
        for _ in range(k):
            p = random.choice(products)
            qty = random.randint(1, 3)
            items.append(OrderItem(sku=p.sku, qty=qty, unit_price_cents=p.price_cents))
        order_id = "ORD-{:08d}".format(i)
        out.append(Order(order_id=order_id, user_id=user.user_id, items=items, created_at=now + i))
    return out


class PricingEngine:
    def __init__(self, tax_rate: float = 0.07) -> None:
        self.tax_rate = tax_rate

    def apply_coupon(self, subtotal_cents: int, code: Optional[str]) -> int:
        if not code:
            return subtotal_cents
        code = code.strip().upper()
        if code == "OFF10":
            return int(subtotal_cents * 0.9)
        if code == "OFF20":
            return int(subtotal_cents * 0.8)
        if code == "FLAT500":
            return max(0, subtotal_cents - 500)
        return subtotal_cents

    def total(self, subtotal_cents: int, coupon: Optional[str] = None) -> int:
        discounted = self.apply_coupon(subtotal_cents, coupon)
        taxed = int(discounted * (1 + self.tax_rate))
        return taxed


class Analytics:
    @staticmethod
    def revenue_series(orders: Iterable[Order]) -> List[int]:
        return [o.subtotal_cents for o in orders]

    @staticmethod
    def mean_revenue(orders: Iterable[Order]) -> float:
        series = Analytics.revenue_series(orders)
        return statistics.mean(series) if series else 0.0

    @staticmethod
    def p95_revenue(orders: Iterable[Order]) -> float:
        series = sorted(Analytics.revenue_series(orders))
        if not series:
            return 0.0
        idx = int(round(0.95 * (len(series) - 1)))
        return float(series[idx])

    @staticmethod
    def top_products(orders: Iterable[Order], top_n: int = 5) -> List[Tuple[str, int]]:
        count: Dict[str, int] = {}
        for o in orders:
            for item in o.items:
                count[item.sku] = count.get(item.sku, 0) + item.qty
        rows = list(count.items())
        rows.sort(key=lambda x: x[1], reverse=True)
        return rows[:top_n]


def render_report(store: InMemoryStore, path: Path) -> None:
    users = list(store.users.values())
    orders = list(store.orders.values())
    products = list(store.products.values())

    rows = {
        "users": len(users),
        "orders": len(orders),
        "products": len(products),
        "mean_revenue": Analytics.mean_revenue(orders),
        "p95_revenue": Analytics.p95_revenue(orders),
        "top_products": Analytics.top_products(orders),
    }

    payload = {
        "summary": rows,
        "hash": stable_hash(json.dumps(rows, sort_keys=True, ensure_ascii=True)),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def rolling_average(values: Sequence[float], window: int) -> List[float]:
    if window <= 0:
        raise ValueError("window must be > 0")
    result: List[float] = []
    for i in range(len(values)):
        left = max(0, i - window + 1)
        span = values[left : i + 1]
        result.append(sum(span) / len(span))
    return result


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def make_random_vector(n: int, seed: int) -> List[float]:
    random.seed(seed)
    return [random.random() for _ in range(n)]


def small_demo() -> Dict[str, object]:
    users = generate_users(25)
    products = generate_products(40)
    orders = generate_orders(users, products, n=120)

    store = InMemoryStore()
    for u in users:
        store.add_user(u)
    for p in products:
        store.add_product(p)
    for o in orders:
        store.add_order(o)

    engine = PricingEngine(tax_rate=0.08)
    priced = [
        engine.total(o.subtotal_cents, coupon="OFF10" if i % 3 == 0 else None)
        for i, o in enumerate(orders)
    ]
    avg = sum(priced) / len(priced)

    va = make_random_vector(128, seed=1)
    vb = make_random_vector(128, seed=2)

    return {
        "users": len(users),
        "products": len(products),
        "orders": len(orders),
        "avg_priced_total": avg,
        "similarity": cosine_similarity(va, vb),
        "rolling_preview": rolling_average([1, 2, 3, 4, 5, 6, 7], window=3),
    }


def large_text_block() -> str:
    lines = []
    alphabet = string.ascii_lowercase
    for i in range(200):
        token = "".join(alphabet[(i + j) % len(alphabet)] for j in range(24))
        lines.append("L{0:04d}: {1}".format(i, token))
    return "\n".join(lines)


def save_large_text(path: Path) -> None:
    path.write_text(large_text_block(), encoding="utf-8")


def run_pipeline(output_dir: Path) -> Dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "report.json"
    blob_path = output_dir / "blob.txt"

    users = generate_users(20)
    products = generate_products(50)
    orders = generate_orders(users, products, 140)

    store = InMemoryStore()
    for obj in itertools.chain(users, products, orders):
        if isinstance(obj, User):
            store.add_user(obj)
        elif isinstance(obj, Product):
            store.add_product(obj)
        elif isinstance(obj, Order):
            store.add_order(obj)

    render_report(store, report_path)
    save_large_text(blob_path)

    summary = {
        "report_path": str(report_path),
        "blob_path": str(blob_path),
        "report_sha": stable_hash(report_path.read_text(encoding="utf-8")),
        "blob_sha": stable_hash(blob_path.read_text(encoding="utf-8")),
    }
    return summary


def main() -> int:
    out = Path("./long_code_demo_output")
    summary = run_pipeline(out)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
