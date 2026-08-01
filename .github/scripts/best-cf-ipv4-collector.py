import ipaddress
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from curl_cffi import requests as cf_requests

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

if TYPE_CHECKING:
    from playwright.sync_api import Browser


SOURCES: dict[str, str] = {
    'https://www.wetest.vip/page/cloudfront/address_v4.html': 'WeTest',
    'https://api.uouin.com/cloudflare.html': 'UOUIN',
    'https://bestcf.pages.dev/xinyitang3/ipv4.txt': 'Mia',
    'https://bestcf.pages.dev/tiancheng/all.txt': 'Tiancheng',
    'https://raw.githubusercontent.com/gslege/CloudflareIP/refs/heads/main/SG.txt': 'Gslege-SG',
    'https://raw.githubusercontent.com/gslege/CloudflareIP/refs/heads/main/DE.txt': 'Gslege-DE',
    'https://raw.githubusercontent.com/gslege/CloudflareIP/refs/heads/main/US.txt': 'Gslege-US',
    'https://raw.githubusercontent.com/ymyuuu/IPDB/refs/heads/main/BestCF/bestcfv4.txt': 'IPDB',
    'https://vps789.com/openApi/cfIpApi': 'VPS789',
    'https://api.4ce.cn/api/bestCFIP': 'vvhan',
}

PORT: str = '443'
HEADERS: dict[str, str] = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0',
}
IPV4_PATTERN: str = r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b'
LOCATION_URL: str = 'https://ipinfo.io/{ip}/country'
OUTPUT_FILE: Path = Path('best-cf-ipv4.txt')
MAX_RETRIES: int = 3
RETRY_BACKOFF_FACTOR: float = 2.0


def _session() -> cf_requests.Session:
    """Create a session with Chrome TLS fingerprint impersonation."""
    session = cf_requests.Session(impersonate='chrome')
    session.headers.update(HEADERS)
    return session


def fetch(session: cf_requests.Session, url: str, timeout: int = 15) -> str:
    """Fetch a URL with retry support and return response text."""
    last_err: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_FACTOR ** attempt)
    assert last_err is not None
    raise last_err


def extract_ipv4(text: str) -> set[str]:
    """Extract valid IPv4 addresses from raw text."""
    ips: set[str] = set()
    for match in re.finditer(IPV4_PATTERN, text):
        try:
            ip = ipaddress.ip_address(match.group())
            ips.add(str(ip))
        except ValueError:
            continue
    return ips


def country_to_flag(code: str) -> str:
    if len(code) != 2 or code == 'XX':
        return ''
    return chr(ord(code[0]) - 65 + 0x1F1E6) + chr(ord(code[1]) - 65 + 0x1F1E6)


def query_location(session: cf_requests.Session, ip: str) -> str:
    """Query country code for an IP via ipinfo.io, return 'XX' on failure."""
    try:
        resp = session.get(LOCATION_URL.format(ip=ip), timeout=10)
        resp.raise_for_status()
        return resp.text.strip()
    except cf_requests.RequestException:
        return 'XX'


def beijing_timestamp() -> str:
    """Return current Beijing time as YYYY-MM-DD HH:MM string."""
    return (datetime.now(timezone.utc) + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M')


_browser = None
_pw = None


def _get_browser() -> 'Browser':
    """Lazily start a reusable headless Chromium instance."""
    global _browser, _pw
    if sync_playwright is None:
        raise RuntimeError('playwright not installed; run: pip install playwright && playwright install chromium')
    if _browser is None:
        _pw = sync_playwright().start()
        _browser = _pw.chromium.launch(headless=True)
    return _browser


def fetch_rendered(url: str, timeout: int = 30000) -> str:
    """Render a JS page with headless Chromium and return the final HTML."""
    context = _get_browser().new_context(user_agent=HEADERS['User-Agent'])
    page = context.new_page()
    try:
        page.goto(url, wait_until='networkidle', timeout=timeout)
        return page.content()
    finally:
        context.close()


def collect_ips(session: cf_requests.Session) -> set[str]:
    """Collect IPv4 from all sources, degrading from HTTP to headless browser.

    A source is considered fetched successfully only when it yields at least
    one valid IPv4 address; otherwise the next fetcher tier is tried.
    """
    all_ips: set[str] = set()
    tiers = [
        ('HTTP', lambda u: fetch(session, u)),
        ('Browser', fetch_rendered),
    ]
    for url, name in SOURCES.items():
        for label, fetcher in tiers:
            try:
                ips = extract_ipv4(fetcher(url))
            except Exception as e:
                print(f'  [{name}] {label} failed: {e}')
                continue
            if ips:
                all_ips.update(ips)
                print(f'  [{name}] {label}: {len(ips)} IPv4')
                break
            print(f'  [{name}] {label}: 0 IPv4, trying next tier')
        else:
            print(f'  [{name}] all fetchers failed')
    return all_ips


def _fetch_location(ip: str) -> tuple[str, str]:
    """Query location for a single IP with its own session."""
    sess = _session()
    try:
        return ip, query_location(sess, ip)
    finally:
        sess.close()


def enrich_locations(ips: set[str]) -> dict[str, str]:
    """Query geographic locations for all IPs concurrently."""
    entries: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=15) as pool:
        fut_map = {pool.submit(_fetch_location, ip): ip for ip in ips}
        for future in as_completed(fut_map):
            ip, location = future.result()
            entries[f'{ip}:{PORT}'] = location
    return entries


def main() -> int:
    """Collect Cloudflare IPs, query locations, and write result file."""
    print('Collecting Cloudflare IPs...\n')

    session = _session()

    all_ips = collect_ips(session)
    if not all_ips:
        print('No IPs collected, skip')
        return 1
    print(f'\n{len(all_ips)} unique IPv4')

    print('Querying locations...')
    entries = enrich_locations(all_ips)

    tmp = OUTPUT_FILE.with_suffix('.tmp')
    timestamp = beijing_timestamp()
    with tmp.open('w', encoding='utf-8') as f:
        f.write(f'#{len(entries)} bestips updated at {timestamp}\n')
        for ip_port, location in entries.items():
            f.write(f'{ip_port}#{location} {country_to_flag(location)}\n')
    tmp.replace(OUTPUT_FILE)
    print(f'\n{len(entries)} IPs written to {OUTPUT_FILE}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
