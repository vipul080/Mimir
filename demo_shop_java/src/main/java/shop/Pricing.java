package shop;

/** Price rules for the shop. */
public final class Pricing {
    public static final double TAX_RATE = 0.18;

    private Pricing() {}

    /** Return the price after a percentage discount. */
    public static double applyDiscount(double price, double percent) {
        return price - price * percent; // bug: percent is 0-100, not 0-1
    }

    /** Add sales tax to a price. */
    public static double addTax(double price) {
        return Math.round(price * (1 + TAX_RATE) * 100) / 100.0;
    }
}
