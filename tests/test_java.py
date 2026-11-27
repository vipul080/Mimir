import os
import shutil
from pathlib import Path

import pytest

from mimir.codemap import CodeMap
from mimir.edits import EditError, replace_symbol
from mimir.feedback import check
from mimir.lang.java import _build_tool

DEMO = Path(__file__).parent.parent / "demo_shop_java"
PRICING = "src/main/java/shop/Pricing.java"
CART = "src/main/java/shop/Cart.java"


@pytest.fixture
def proj(tmp_path):
    dst = tmp_path / "demo_shop_java"
    shutil.copytree(DEMO, dst, ignore=shutil.ignore_patterns("target"))
    return dst


def test_repo_map_lists_classes_records_and_methods(proj):
    out = CodeMap(proj).repo_map()
    assert "languages: java" in out
    assert "Cart[Cart, add, subtotal, total]" in out
    assert "Cart.Item" in out
    assert "Pricing[Pricing, applyDiscount, addTax]" in out


def test_outline_has_signatures_javadoc_and_no_bodies(proj):
    out = CodeMap(proj).outline(CART)
    assert "public double total()   // Final amount to pay" in out
    assert "public record Item(String name, double price, int qty)" in out
    assert "imports: java.util.{ArrayList, List}" in out
    assert "stream()" not in out


def test_overloads_and_line_picker(proj):
    cm = CodeMap(proj)
    hits = cm.find("Cart.add")
    assert len(hits) == 2
    assert len(cm.find(f"Cart.add@{hits[1].start}")) == 1
    assert cm.find(f"{PRICING}:applyDiscount")[0].kind == "method"


def test_callers_include_constructors_and_methods(proj):
    cm = CodeMap(proj)
    assert {c.file for c in cm.callers("applyDiscount")} == {CART, "src/test/java/shop/CartTest.java"}
    assert any(c.caller == "Cart.add" for c in cm.callers("Item"))  # new Item(...)


def test_broken_java_edit_is_refused(proj):
    before = (proj / PRICING).read_text()
    with pytest.raises(EditError, match="syntax error"):
        replace_symbol(CodeMap(proj), "Pricing.applyDiscount",
                       "public static double applyDiscount(double p, double x) {\n  return p - ;\n}")
    assert (proj / PRICING).read_text() == before


def test_ambiguous_overload_is_refused_with_choices(proj):
    with pytest.raises(EditError, match=r"Cart\.add@\d+"):
        replace_symbol(CodeMap(proj), "Cart.add", "void add() {}")


def test_edit_keeps_indentation_and_javadoc(proj):
    replace_symbol(CodeMap(proj), "Pricing.applyDiscount",
                   "public static double applyDiscount(double price, double percent) {\n"
                   "    return price - price * percent / 100;\n}\n")
    text = (proj / PRICING).read_text()
    assert "    /** Return the price after a percentage discount. */\n" \
           "    public static double applyDiscount(double price, double percent) {\n" \
           "        return price - price * percent / 100;\n    }" in text


def test_syntax_check_without_tests(proj):
    (proj / PRICING).write_text("class Pricing { void x( { }")
    out = check(CodeMap(proj), [PRICING], run_tests=False)
    assert out.startswith("RESULT: FAIL") and "SYNTAX (java): FAIL" in out


@pytest.mark.skipif(_build_tool(DEMO) is None, reason="Maven not available (set MIMIR_MAVEN)")
def test_maven_tests_fail_then_pass(proj):
    cm = CodeMap(proj)
    before = check(cm)
    assert "TESTS (maven, full suite): FAIL" in before
    assert "CartTest.discount" in before
    assert "expected: <180.0> but was: <-1800.0>" in before
    assert "at shop.CartTest.discount(CartTest.java:17)" in before
    assert "Tests run: 3, Failures: 2" in before
    replace_symbol(cm, "Pricing.applyDiscount",
                   "public static double applyDiscount(double price, double percent) {\n"
                   "    return price - price * percent / 100;\n}\n")
    after = check(cm, [PRICING])
    assert after.startswith("RESULT: ok"), after
    assert "1 related test class(es)" in after


def test_junit_xml_failures_are_explained(tmp_path):
    """Mockito spreads call arguments over several lines; they are folded back."""
    from mimir.lang.java import _junit_failures
    (tmp_path / "TEST-shop.PayTest.xml").write_text("""<?xml version="1.0"?>
<testsuite name="shop.PayTest">
  <testcase name="capturesInPaise" classname="shop.PayTest">
    <failure message="&#10;Argument(s) are different! Wanted:&#10;gateway.createOrder(&#10;    150000L,&#10;    &quot;b_1&quot;&#10;);&#10;-&gt; at shop.PayTest.capturesInPaise(PayTest.java:12)&#10;Actual invocations have different arguments:&#10;gateway.createOrder(&#10;    1500L,&#10;    &quot;b_1&quot;&#10;);&#10;-&gt; at shop.Pay.create(Pay.java:40)" type="org.mockito.exceptions.verification.ArgumentsAreDifferent">stack</failure>
  </testcase>
  <testcase name="passes" classname="shop.PayTest"/>
</testsuite>""")
    [report] = _junit_failures([tmp_path], since=0)
    assert report.startswith("PayTest.capturesInPaise")
    assert 'gateway.createOrder(150000L, "b_1");' in report
    assert 'gateway.createOrder(1500L, "b_1");' in report
    assert "-> at shop.Pay.create(Pay.java:40)" in report


def test_javadoc_first_sentence_is_complete(tmp_path):
    (tmp_path / "A.java").write_text(
        "class A {\n"
        "    /**\n"
        "     * Owner may call off a booking\n"
        "     * (e.g. machine broke down). Second sentence.\n"
        "     * @param x ignored\n"
        "     */\n"
        "    void cancel() {}\n"
        "}\n")
    out = CodeMap(tmp_path).outline("A.java")
    assert "// Owner may call off a booking (e.g. machine broke down)." in out
    assert "Second sentence" not in out


def test_no_build_tool_is_reported_not_crashed(tmp_path, monkeypatch):
    monkeypatch.delenv("MIMIR_MAVEN", raising=False)
    monkeypatch.setenv("PATH", "")
    (tmp_path / "A.java").write_text("class A { int f() { return 1; } }")
    out = check(CodeMap(tmp_path))
    assert out.startswith("RESULT: ok") and "skipped" in out
    assert os.environ["PATH"] == ""
