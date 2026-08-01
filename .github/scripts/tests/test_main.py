"""End-to-end test for main(): full pipeline with all network/IO mocked."""


class TestMain:
    def test_writes_formatted_output_file(self, collector, monkeypatch, tmp_path):
        output = tmp_path / 'best-cf-ipv4.txt'
        monkeypatch.setattr(collector, 'OUTPUT_FILE', output)
        monkeypatch.setattr(collector, '_session', lambda: object())
        monkeypatch.setattr(collector, 'collect_ips', lambda s: {'1.2.3.4', '5.6.7.8'})
        monkeypatch.setattr(collector, 'enrich_locations', lambda ips: {
            '1.2.3.4:443': 'US',
            '5.6.7.8:443': 'CN',
        })
        monkeypatch.setattr(collector, 'beijing_timestamp', lambda: '2026-08-01 12:00')

        assert collector.main() == 0

        lines = output.read_text(encoding='utf-8').splitlines()
        assert lines[0] == '#2 bestips updated at 2026-08-01 12:00'
        assert lines[1] == '1.2.3.4:443#US \U0001F1FA\U0001F1F8'
        assert lines[2] == '5.6.7.8:443#CN \U0001F1E8\U0001F1F3'

    def test_returns_1_when_no_ips_collected(self, collector, monkeypatch, tmp_path):
        monkeypatch.setattr(collector, 'OUTPUT_FILE', tmp_path / 'best-cf-ipv4.txt')
        monkeypatch.setattr(collector, 'collect_ips', lambda s: set())
        monkeypatch.setattr(collector, 'enrich_locations', lambda ips: (_ for _ in ()).throw(AssertionError('must not run')))

        assert collector.main() == 1
        assert not (tmp_path / 'best-cf-ipv4.txt').exists()

    def test_contains_all_entries_regardless_of_iteration_order(self, collector, monkeypatch, tmp_path):
        """All IPs must appear in the file even if set iteration order differs."""
        output = tmp_path / 'best-cf-ipv4.txt'
        monkeypatch.setattr(collector, 'OUTPUT_FILE', output)
        monkeypatch.setattr(collector, 'collect_ips', lambda s: {'1.1.1.1', '2.2.2.2', '3.3.3.3'})
        monkeypatch.setattr(collector, 'enrich_locations', lambda ips: {
            f'{ip}:443': 'XX' for ip in ips
        })
        monkeypatch.setattr(collector, 'beijing_timestamp', lambda: '2026-08-01 12:00')

        assert collector.main() == 0

        body = output.read_text(encoding='utf-8').splitlines()[1:]
        assert set(body) == {'1.1.1.1:443#XX ', '2.2.2.2:443#XX ', '3.3.3.3:443#XX '}

    def test_atomic_write_leaves_no_tmp_file(self, collector, monkeypatch, tmp_path):
        output = tmp_path / 'best-cf-ipv4.txt'
        monkeypatch.setattr(collector, 'OUTPUT_FILE', output)
        monkeypatch.setattr(collector, 'collect_ips', lambda s: {'1.2.3.4'})
        monkeypatch.setattr(collector, 'enrich_locations', lambda ips: {'1.2.3.4:443': 'US'})
        monkeypatch.setattr(collector, 'beijing_timestamp', lambda: '2026-08-01 12:00')

        collector.main()
        assert output.exists()
        assert not output.with_suffix('.tmp').exists()
