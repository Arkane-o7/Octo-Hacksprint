from datetime import datetime, timezone

import pytest

from octo.notice_dates import resolve_notice_date

STAMP = datetime(2026, 10, 17, 20, tzinfo=timezone.utc)  # Sunday Oct 18 in India.


@pytest.mark.parametrize('written,expected', [
    ('24th October', '2026-10-24'), ('October 24th', '2026-10-24'),
    ('on 24th of October', '2026-10-24'), ('24 Oct 2027', '2027-10-24'),
    ('24th October 2026', '2026-10-24'), ('October 24, 2026', '2026-10-24'),
    ('2026-10-24', '2026-10-24'), ('upcoming Friday', '2026-10-23'),
    ('next Friday', '2026-10-23'), ('this Friday', '2026-10-23'),
    ('today', '2026-10-18'), ('tomorrow', '2026-10-19'),
    ('day after tomorrow', '2026-10-20'), ('Sunday', '2026-10-18'),
    ('upcoming Sunday', '2026-10-25'), ('31st February', None),
    ('10/11/2026', None), (None, None),
])
def test_notice_dates_override_incorrect_model_arithmetic(written, expected):
    assert resolve_notice_date(written, STAMP, '2099-01-01') == expected


def test_weekdays_cross_year_boundary_but_yearless_dates_do_not_invent_future_year():
    stamp = datetime(2026, 12, 31, 6, tzinfo=timezone.utc)
    assert resolve_notice_date('upcoming Friday', stamp) == '2027-01-01'
    assert resolve_notice_date('24th October', stamp) == '2026-10-24'


def test_other_language_retains_valid_model_resolution():
    assert resolve_notice_date('अगले शुक्रवार', STAMP, '2026-10-23') == '2026-10-23'
    assert resolve_notice_date('अगले शुक्रवार', STAMP, 'not-a-date') is None
