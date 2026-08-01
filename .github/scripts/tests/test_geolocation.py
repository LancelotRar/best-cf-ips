"""Tests for offline geolocation: lookup_country, enrich_locations, _ensure_xdb."""

import pytest


class FakeSearcher:
    """Seacher stand-in; raise Exception instance via `raises` for error cases."""

    def __init__(self, region):
        self.region = region

    def search(self, ip):
        if isinstance(self.region, Exception):
            raise self.region
        return self.region


class TestLookupCountry:
    def test_returns_iso_code_from_region(self, collector, monkeypatch):
        monkeypatch.setattr(collector, '_get_searcher', lambda: FakeSearcher('United States|California|0|0|US'))
        assert collector.lookup_country('1.2.3.4') == 'US'

    def test_returns_xx_for_reserved(self, collector, monkeypatch):
        monkeypatch.setattr(collector, '_get_searcher', lambda: FakeSearcher('Reserved|Reserved|Reserved|0|0'))
        assert collector.lookup_country('1.2.3.4') == 'XX'

    def test_returns_xx_for_legacy_format_without_code(self, collector, monkeypatch):
        monkeypatch.setattr(collector, '_get_searcher', lambda: FakeSearcher('美国|加利福尼亚州|洛杉矶|专线用户'))
        assert collector.lookup_country('1.2.3.4') == 'XX'

    def test_returns_xx_for_empty_region(self, collector, monkeypatch):
        monkeypatch.setattr(collector, '_get_searcher', lambda: FakeSearcher(''))
        assert collector.lookup_country('1.2.3.4') == 'XX'

    def test_returns_xx_when_search_raises(self, collector, monkeypatch):
        monkeypatch.setattr(collector, '_get_searcher', lambda: FakeSearcher(RuntimeError('bad ip')))
        assert collector.lookup_country('not-an-ip') == 'XX'

    def test_returns_xx_when_searcher_creation_fails(self, collector, monkeypatch):
        monkeypatch.setattr(collector, '_get_searcher', lambda: (_ for _ in ()).throw(RuntimeError('no xdb')))
        assert collector.lookup_country('1.2.3.4') == 'XX'


class TestEnrichLocations:
    def test_produces_ip_port_to_code_entries(self, collector, monkeypatch):
        monkeypatch.setattr(collector, '_get_searcher', lambda: FakeSearcher('中国|广东省|深圳市|移动|CN'))
        entries = collector.enrich_locations({'1.2.3.4', '5.6.7.8'})
        assert entries == {
            '1.2.3.4:443': 'CN',
            '5.6.7.8:443': 'CN',
        }

    def test_preserves_xx_for_unknown(self, collector, monkeypatch):
        monkeypatch.setattr(collector, '_get_searcher', lambda: FakeSearcher('Reserved|Reserved|Reserved|0|0'))
        assert collector.enrich_locations({'1.2.3.4'}) == {'1.2.3.4:443': 'XX'}


class TestEnsureXdb:
    def test_skips_download_when_file_exists(self, collector, monkeypatch, tmp_path):
        xdb = tmp_path / 'ip2region_v4.xdb'
        xdb.write_bytes(b'fake')
        monkeypatch.setattr(collector, 'XDB_FILE', xdb)
        monkeypatch.setattr(collector, '_session', lambda: (_ for _ in ()).throw(AssertionError('must not call session')))
        collector._ensure_xdb()

    def test_downloads_when_missing(self, collector, monkeypatch, tmp_path):
        xdb = tmp_path / 'sub' / 'ip2region_v4.xdb'
        monkeypatch.setattr(collector, 'XDB_FILE', xdb)
        monkeypatch.setattr(collector, 'XDB_URL', 'http://example.com/ip2region_v4.xdb')

        class FakeResponse:
            content = b'xdb-bytes'

            def raise_for_status(self):
                pass

        class FakeSession:
            def __init__(self):
                self.closed = False

            def get(self, url, timeout):
                assert url == 'http://example.com/ip2region_v4.xdb'
                assert timeout == 120
                return FakeResponse()

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                self.closed = True

        session = FakeSession()
        monkeypatch.setattr(collector, '_session', lambda: session)
        collector._ensure_xdb()
        assert xdb.read_bytes() == b'xdb-bytes'
        assert session.closed

    def test_raises_when_download_fails(self, collector, monkeypatch, tmp_path):
        xdb = tmp_path / 'ip2region_v4.xdb'
        monkeypatch.setattr(collector, 'XDB_FILE', xdb)
        monkeypatch.setattr(collector, 'XDB_URL', 'http://example.com/ip2region_v4.xdb')

        class FakeResponse:
            def raise_for_status(self):
                raise RuntimeError('HTTP 500')

        class FakeSession:
            def get(self, url, timeout):
                return FakeResponse()

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                pass

        monkeypatch.setattr(collector, '_session', lambda: FakeSession())
        with pytest.raises(RuntimeError, match='HTTP 500'):
            collector._ensure_xdb()
        assert not xdb.exists()
