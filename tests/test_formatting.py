"""Time, count and date formatting."""

import pytest

from clipper_app.formatting import format_count, format_date, format_time, parse_time


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "0:00"),
        (5, "0:05"),
        (65, "1:05"),
        (599.6, "10:00"),
        (3723, "1:02:03"),
        (None, "0:00"),
        (-4, "0:00"),
        (float("nan"), "0:00"),
    ],
)
def test_format_time(seconds, expected):
    assert format_time(seconds) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("83", 83.0),
        ("1:23", 83.0),
        ("01:23", 83.0),
        ("75:00", 4500.0),
        ("1:02:03", 3723.0),
        ("1:23.5", 83.5),
        ("1:23,5", 83.5),
        (" 2:00 ", 120.0),
    ],
)
def test_parse_time(text, expected):
    assert parse_time(text) == pytest.approx(expected)


@pytest.mark.parametrize(
    "text",
    ["", "  ", "abc", "1:60", "1:2:3:4", "-5", "1::2", "1.5:20", "1:61:00", "inf"],
)
def test_parse_time_rejects_invalid(text):
    with pytest.raises(ValueError):
        parse_time(text)


def test_round_trip():
    for seconds in (0, 59, 61, 600, 3599, 3600, 7322):
        assert parse_time(format_time(seconds)) == seconds


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, "0"),
        (999, "999"),
        (433000, "433,000"),
        (1234567, "1,234,567"),
        (None, "-"),
        ("x", "-"),
    ],
)
def test_format_count(value, expected):
    assert format_count(value) == expected


def test_format_date():
    assert format_date("20261015") == "2026-10-15"
    assert format_date(None) == "-"
    assert format_date("bad") == "-"
    assert format_date(None, 1791590400, approximate=True).startswith("~")
    assert format_date(None, 1791590400).startswith("2026-")
