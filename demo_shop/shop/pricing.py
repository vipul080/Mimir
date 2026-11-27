"""Price rules for the shop."""

TAX_RATE = 0.18


def apply_discount(price: float, percent: float) -> float:
    """Return the price after a percentage discount."""
    return price - price * percent  # bug: percent is 0-100, not 0-1


def add_tax(price: float) -> float:
    """Add sales tax to a price."""
    return round(price * (1 + TAX_RATE), 2)
