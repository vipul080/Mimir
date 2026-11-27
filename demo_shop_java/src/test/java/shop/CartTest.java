package shop;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

class CartTest {
    @Test
    void subtotal() {
        Cart c = new Cart();
        c.add("pen", 10, 3);
        assertEquals(30.0, c.subtotal());
    }

    @Test
    void discount() {
        assertEquals(180.0, Pricing.applyDiscount(200, 10));
    }

    @Test
    void totalWithDiscount() {
        Cart c = new Cart(50);
        c.add("book", 100);
        assertEquals(59.0, c.total());
    }
}
