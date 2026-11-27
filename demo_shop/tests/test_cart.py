from shop.cart import Cart
from shop.pricing import apply_discount


def test_subtotal():
    c = Cart()
    c.add("pen", 10, 3)
    assert c.subtotal() == 30


def test_discount():
    assert apply_discount(200, 10) == 180


def test_total_with_discount():
    c = Cart(discount_percent=50)
    c.add("book", 100)
    assert c.total() == 59.0
