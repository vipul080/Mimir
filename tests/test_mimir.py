import shutil
from pathlib import Path

import pytest

from mimir.checkpoints import Checkpoints
from mimir.codemap import CodeMap
from mimir.edits import EditError, replace_symbol
from mimir.feedback import check

DEMO = Path(__file__).parent.parent / "demo_shop"


@pytest.fixture
def proj(tmp_path):
    dst = tmp_path / "demo_shop"
    shutil.copytree(DEMO, dst)
    return dst


def test_repo_map_and_outline(proj):
    cm = CodeMap(proj)
    assert "Cart[add, subtotal, total]" in cm.repo_map()
    out = cm.outline("shop/cart.py")
    assert "def total(self) -> float" in out and "sum(" not in out  # bodies hidden


def test_find_forms(proj):
    cm = CodeMap(proj)
    assert cm.find("Cart.total")[0].kind == "method"
    assert cm.find("total")[0].qualname == "Cart.total"
    assert cm.find("shop/pricing.py:add_tax")[0].file == "shop/pricing.py"
    assert cm.find("nope") == []


def test_callers(proj):
    files = {c.file for c in CodeMap(proj).callers("apply_discount")}
    assert files == {"shop/cart.py", "tests/test_cart.py"}


def test_bad_edit_rejected_and_file_untouched(proj):
    before = (proj / "shop/pricing.py").read_text()
    with pytest.raises(EditError):
        replace_symbol(CodeMap(proj), "apply_discount", "def apply_discount(:\n  pass")
    assert (proj / "shop/pricing.py").read_text() == before


def test_edit_reindents_methods(proj):
    cm = CodeMap(proj)
    replace_symbol(cm, "Cart.subtotal", "def subtotal(self):\n    return 0\n")
    assert "    def subtotal(self):\n        return 0" in (proj / "shop/cart.py").read_text()


def test_fix_makes_check_pass(proj):
    cm = CodeMap(proj)
    assert check(cm).startswith("RESULT: FAIL")
    replace_symbol(cm, "apply_discount", "def apply_discount(price, percent):\n"
                                         "    return price - price * percent / 100\n")
    assert check(cm).startswith("RESULT: ok")


def test_checkpoint_restore_roundtrip(proj):
    cps = Checkpoints(proj)
    cp = cps.create("start")
    (proj / "shop/pricing.py").write_text("x = 1\n")
    (proj / "shop/new.py").write_text("y = 2\n")
    ch = cps.changes(cp)
    assert ch["modified"] == ["shop/pricing.py"] and ch["added"] == ["shop/new.py"]
    r = cps.restore(cp)
    assert not (proj / "shop/new.py").exists()
    assert "apply_discount" in (proj / "shop/pricing.py").read_text()
    assert not any(cps.changes(cp).values())
    # the restore itself can be undone
    cps.restore(r["safety_checkpoint"])
    assert (proj / "shop/new.py").exists()
