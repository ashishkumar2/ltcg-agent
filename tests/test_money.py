import pytest

from ltcg_agent.models.money import Currency, Money


def test_add_same_currency_returns_sum():
    a = Money(amount=100, currency=Currency.INR)
    b = Money(amount=200, currency=Currency.INR)
    assert (a + b) == Money(amount=300, currency=Currency.INR)


def test_add_different_currency_raises_type_error():
    a = Money(amount=100, currency=Currency.INR)
    b = Money(amount=100, currency=Currency.USD)
    with pytest.raises(TypeError, match="Currency mismatch"):
        _ = a + b


def test_sub_same_currency_returns_difference():
    a = Money(amount=500, currency=Currency.USD)
    b = Money(amount=200, currency=Currency.USD)
    assert (a - b) == Money(amount=300, currency=Currency.USD)


def test_mul_scalar():
    m = Money(amount=100, currency=Currency.USD)
    assert m * 3 == Money(amount=300, currency=Currency.USD)


def test_zero_factory():
    z = Money.zero(Currency.INR)
    assert z.amount == 0
    assert z.currency == Currency.INR


def test_from_major_units_rounds_to_cents():
    m = Money.from_major_units(10.999, Currency.USD)
    assert m.amount == 1100


def test_to_major_units():
    m = Money(amount=12345, currency=Currency.INR)
    assert m.to_major_units() == 123.45


def test_convert_to_inr_uses_ttbr():
    usd = Money(amount=100_00, currency=Currency.USD)
    ttbr_paise = 8400_00
    inr = usd.convert_to_inr(ttbr_paise)
    assert inr.currency == Currency.INR
    assert inr.amount == 840000_00


def test_convert_to_inr_rejects_non_usd():
    inr = Money(amount=100, currency=Currency.INR)
    with pytest.raises(TypeError):
        inr.convert_to_inr(8400_00)


def test_repr_positive():
    m = Money(amount=1099, currency=Currency.USD)
    assert repr(m) == "$10.99"


def test_repr_negative():
    m = Money(amount=-1099, currency=Currency.USD)
    assert repr(m) == "-$10.99"


def test_equality_and_hash():
    a = Money(amount=500, currency=Currency.INR)
    b = Money(amount=500, currency=Currency.INR)
    assert a == b
    assert hash(a) == hash(b)
