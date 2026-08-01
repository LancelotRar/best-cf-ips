"""Tests for network fetching: fetch retry logic and collect_ips tier degradation."""

import pytest


class FakeResponse:
    """Minimal stand-in for curl_cffi response objects."""

    def __init__(self, text='', status=200):
        self.text = text
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f'HTTP {self.status_code}')


class FakeSession:
    def __init__(self, responses=(), getter=None):
        self._responses = list(responses)
        self._getter = getter

    def get(self, url, timeout=None):
        if self._getter is not None:
            return self._getter(url, timeout)
        return self._responses.pop(0)


class TestFetch:
    def test_returns_text_on_success(self, collector):
        session = FakeSession([FakeResponse(text='ok')])
        assert collector.fetch(session, 'http://example.com') == 'ok'

    def test_retries_then_succeeds(self, collector, monkeypatch):
        calls = []
        sleeps = []
        monkeypatch.setattr(collector.time, 'sleep', sleeps.append)

        def fake_get(url, timeout):
            calls.append(1)
            if len(calls) == 1:
                raise ConnectionError('boom')
            return FakeResponse(text='ok')

        session = FakeSession(getter=fake_get)
        assert collector.fetch(session, 'http://example.com') == 'ok'
        assert len(calls) == 2
        assert sleeps == [collector.RETRY_BACKOFF_FACTOR ** 1]

    def test_raises_last_error_after_all_retries(self, collector, monkeypatch):
        monkeypatch.setattr(collector.time, 'sleep', lambda s: None)

        def boom(url, timeout):
            raise ConnectionError('boom')

        with pytest.raises(ConnectionError):
            collector.fetch(FakeSession(getter=boom), 'http://example.com')

    def test_retry_backoff_scales(self, collector, monkeypatch):
        sleeps = []
        monkeypatch.setattr(collector.time, 'sleep', sleeps.append)

        def boom(url, timeout):
            raise ConnectionError('boom')

        with pytest.raises(ConnectionError):
            collector.fetch(FakeSession(getter=boom), 'http://example.com')
        assert sleeps == [collector.RETRY_BACKOFF_FACTOR ** 1, collector.RETRY_BACKOFF_FACTOR ** 2]


class TestCollectIps:
    def test_aggregates_and_deduplicates(self, collector, monkeypatch):
        monkeypatch.setattr(collector, 'SOURCES', {
            'http://a.example': 'A',
            'http://b.example': 'B',
        })
        monkeypatch.setattr(collector, 'fetch', lambda s, u, timeout=15: {
            'http://a.example': '1.1.1.1\n2.2.2.2',
            'http://b.example': '2.2.2.2\n3.3.3.3',
        }[u])
        monkeypatch.setattr(collector, 'fetch_rendered', lambda u, timeout=30000: '')
        assert collector.collect_ips(object()) == {'1.1.1.1', '2.2.2.2', '3.3.3.3'}

    def test_degrades_to_browser_on_http_failure(self, collector, monkeypatch):
        monkeypatch.setattr(collector, 'SOURCES', {'http://a.example': 'A'})
        monkeypatch.setattr(collector, 'fetch', lambda s, u, timeout=15: (_ for _ in ()).throw(ConnectionError('down')))
        monkeypatch.setattr(collector, 'fetch_rendered', lambda u, timeout=30000: '9.9.9.9')
        assert collector.collect_ips(object()) == {'9.9.9.9'}

    def test_degrades_to_browser_when_http_has_no_ips(self, collector, monkeypatch):
        monkeypatch.setattr(collector, 'SOURCES', {'http://a.example': 'A'})
        monkeypatch.setattr(collector, 'fetch', lambda s, u, timeout=15: 'no ips here')
        monkeypatch.setattr(collector, 'fetch_rendered', lambda u, timeout=30000: '8.8.8.8')
        assert collector.collect_ips(object()) == {'8.8.8.8'}

    def test_skips_source_when_all_tiers_fail(self, collector, monkeypatch):
        monkeypatch.setattr(collector, 'SOURCES', {'http://a.example': 'A'})
        monkeypatch.setattr(collector, 'fetch', lambda s, u, timeout=15: (_ for _ in ()).throw(ConnectionError('down')))
        monkeypatch.setattr(collector, 'fetch_rendered', lambda u, timeout=30000: (_ for _ in ()).throw(RuntimeError('no browser')))
        assert collector.collect_ips(object()) == set()

    def test_stops_at_first_tier_with_ips(self, collector, monkeypatch):
        """Browser tier must not run when HTTP already yielded IPs."""
        rendered_calls = []

        def fetch_rendered(url, timeout=30000):
            rendered_calls.append(url)
            return ''

        monkeypatch.setattr(collector, 'SOURCES', {'http://a.example': 'A'})
        monkeypatch.setattr(collector, 'fetch', lambda s, u, timeout=15: '1.1.1.1')
        monkeypatch.setattr(collector, 'fetch_rendered', fetch_rendered)
        collector.collect_ips(object())
        assert rendered_calls == []
