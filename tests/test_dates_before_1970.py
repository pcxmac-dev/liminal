"""Times before 1970 on every platform: datetime.fromtimestamp refuses a negative time on Windows
up to Python 3.14 (OSError 22), and the datasets reach back to 1871 (Shiller) and 1926 (French)."""
from datetime import date, datetime, timezone

from liminal_libs.sources import dataset


def test_a_day_before_1970_is_dated_by_arithmetic_from_the_epoch():
    first = date(1871, 1, 1)
    assert dataset.day_of(dataset.ms(first)) == first
    assert dataset.day_of(dataset.ms(first) - 1) == date(1870, 12, 31)  # the ms before its midnight, US/Eastern
    assert dataset.day_of(dataset.ms(date(1926, 7, 1))) == date(1926, 7, 1)
    assert dataset.day_of(0) == date(1969, 12, 31)  # the epoch is 19:00 the day before in New York
    assert dataset.EPOCH == datetime(1970, 1, 1, tzinfo=timezone.utc)


def test_a_publication_rule_dates_a_period_before_1970():
    rule = dataset.months_after(1, 15)  # the 15th of the month after the period's
    assert dataset.day_of(rule(dataset.ms(date(1871, 1, 1)))) == date(1871, 2, 15)
    assert dataset.day_of(rule(dataset.ms(date(1969, 12, 1)))) == date(1970, 1, 15)
