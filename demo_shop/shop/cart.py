"""Shopping cart."""
from dataclasses import dataclass, field

from .pricing import add_tax, apply_discount


@dataclass
class Item:
    name: str
    price: float
    qty: int = 1


@dataclass
class Cart:
    items: list[Item] = field(default_factory=list)
    discount_percent: float = 0

    def add(self, name: str, price: float, qty: int = 1) -> None:
        """Add an item to the cart."""
        self.items.append(Item(name, price, qty))

    def subtotal(self) -> float:
        """Sum of item prices before discount and tax."""
        return sum(i.price * i.qty for i in self.items)

    def total(self) -> float:
        """Final amount to pay: discount first, then tax."""
        return add_tax(apply_discount(self.subtotal(), self.discount_percent))
