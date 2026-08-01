"""Tests for pure utility functions: extract_ipv4, country_to_flag, beijing_timestamp."""

import re
from datetime import datetime


class TestExtractIpv4:
    def test_extracts_valid_ips(self, collector):
        assert collector.extract_ipv4('104.16.132.229\n172.64.0.1') == {
            '104.16.132.229', '172.64.0.1',
        }

    def test_deduplicates(self, collector):
        assert collector.extract_ipv4('1.2.3.4 1.2.3.4 1.2.3.4') == {'1.2.3.4'}

    def test_ignores_invalid_octets(self, collector):
        assert collector.extract_ipv4('999.999.999.999 256.1.1.1 1.2.3') == set()

    def test_extracts_from_html(self, collector):
        html = '<td>104.16.132.229</td><a href="/ip/172.64.0.1">link</a>'
        assert collector.extract_ipv4(html) == {'104.16.132.229', '172.64.0.1'}

    def test_extracts_from_ip_port_list(self, collector):
        assert collector.extract_ipv4('104.16.132.229:443#US 1.1.1.1:80') == {
            '104.16.132.229', '1.1.1.1',
        }

    def test_empty_text(self, collector):
        assert collector.extract_ipv4('') == set()

    def test_no_ipv6(self, collector):
        assert collector.extract_ipv4('2606:4700::1111') == set()


class TestCountryToFlag:
    def test_us_flag(self, collector):
        assert collector.country_to_flag('US') == '\U0001F1FA\U0001F1F8'

    def test_cn_flag(self, collector):
        assert collector.country_to_flag('CN') == '\U0001F1E8\U0001F1F3'

    def test_xx_returns_empty(self, collector):
        assert collector.country_to_flag('XX') == ''

    def test_wrong_length_returns_empty(self, collector):
        assert collector.country_to_flag('USA') == ''
        assert collector.country_to_flag('U') == ''


class TestBeijingTimestamp:
    def _freeze(self, collector, monkeypatch, utc_now):
        class FakeDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(utc_now.year, utc_now.month, utc_now.day,
                                utc_now.hour, utc_now.minute, tzinfo=tz)

        monkeypatch.setattr(collector, 'datetime', FakeDatetime)

    def test_format(self, collector):
        ts = collector.beijing_timestamp()
        assert re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}', ts)

    def test_utc_to_beijing_rollover(self, collector, monkeypatch):
        self._freeze(collector, monkeypatch, datetime(2026, 8, 1, 16, 30))
        assert collector.beijing_timestamp() == '2026-08-02 00:30'

    def test_uses_utc_aware_time(self, collector, monkeypatch):
        self._freeze(collector, monkeypatch, datetime(2026, 1, 1, 0, 0))
        assert collector.beijing_timestamp() == '2026-01-01 08:00'
