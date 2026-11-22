"""Checked fixed precision conversion with source text retained separately."""

from decimal import Decimal, InvalidOperation


class NumericRangeError(ValueError):
    pass


def checked_decimal(text: str | None, *, precision: int = 38, scale: int = 12) -> Decimal | None:
    if not (1 <= precision <= 38 and 0 <= scale <= min(precision, 37)):
        raise ValueError("Unsupported fixed precision specification")
    if text is None:
        return None
    if not isinstance(text, str):
        raise NumericRangeError("Numeric input must be exact decimal text")
    try:
        number = Decimal(text)
    except (InvalidOperation, TypeError):
        raise NumericRangeError("Invalid decimal text") from None
    if not number.is_finite():
        raise NumericRangeError("Non-finite decimal")
    if number.is_zero():
        return Decimal(0)
    # Inspect significant digits directly; Decimal quantize can round under the
    # process-wide decimal context, even before the database sees the value.
    sign, digits, exponent = number.as_tuple()
    while digits[-1] == 0:
        digits, exponent = digits[:-1], exponent + 1
    fractional = max(0, -exponent)
    integer = max(0, len(digits) + exponent)
    if fractional > scale or integer > precision - scale:
        raise NumericRangeError("Value exceeds fixed precision or scale")
    return number
