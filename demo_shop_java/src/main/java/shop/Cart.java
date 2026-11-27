package shop;

import java.util.ArrayList;
import java.util.List;

/** Shopping cart. */
public class Cart {
    /** One line in the cart. */
    public record Item(String name, double price, int qty) {}

    private final List<Item> items = new ArrayList<>();
    private final double discountPercent;

    public Cart() {
        this(0);
    }

    public Cart(double discountPercent) {
        this.discountPercent = discountPercent;
    }

    /** Add one unit of an item. */
    public void add(String name, double price) {
        add(name, price, 1);
    }

    /** Add an item to the cart. */
    public void add(String name, double price, int qty) {
        items.add(new Item(name, price, qty));
    }

    /** Sum of item prices before discount and tax. */
    public double subtotal() {
        return items.stream().mapToDouble(i -> i.price() * i.qty()).sum();
    }

    /** Final amount to pay: discount first, then tax. */
    public double total() {
        return Pricing.addTax(Pricing.applyDiscount(subtotal(), discountPercent));
    }
}
