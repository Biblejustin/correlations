import datetime as dt
import fcntl
import json
from pathlib import Path
import tempfile
import unittest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ops' / 'vps'))
import monthly_release_review as review


DAY = dt.date(2026, 9, 6)


def cru(version="4.10", extra=""):
    return f'''<h3>Announcements &amp; News</h3><ul>
    <li><a>25 June 2026 CRU-TS v{version} and <b>CRU-CY</b>
      v{version} released</a></li>
    <li>27 June 2024 CRU-TS v4.08 released</li></ul>{extra}'''.encode()


def ucdp(version="26.1", extra=""):
    return f'''<h3>UCDP Candidate Events Dataset version 99.0.9</h3>
    <a href="/downloads/candidateged/ged2610-csv.zip">Candidate CSV</a>
    <h3>UCDP Country-Year Dataset on Organized Violence within Country Borders version {version}</h3>
    <a href="/downloads/organizedviolencecy/organizedviolencecy-{version.replace('.', '')}-csv.zip">CSV</a>{extra}'''.encode()


def vdem(version="16", extra=""):
    return f'''<h3>Country-Year: V-Dem Full+Others</h3><p>Version 99 Published March 2026</p>
    <h3>Country-Year: V-Dem Core</h3><table><tr><th>Version</th><td>{version}</td></tr>
    <tr><th>Published</th><td>March 2026</td></tr></table>{extra}
    <h3>Country-Date: V-Dem</h3><p>Version 98 Published March 2026</p>'''.encode()


def fetcher(pages, calls):
    def fetch(url):
        calls.append(url)
        source_id = next(k for k, v in review.SOURCES.items() if v['url'] == url)
        payload = pages[source_id]
        if isinstance(payload, BaseException):
            raise payload
        return payload
    return fetch


PAGES = {'cru_cy': cru(), 'ucdp_annual': ucdp(), 'vdem_core': vdem()}


class ReleaseParsingTests(unittest.TestCase):
    def test_current_exact_products_ignore_other_versions(self):
        self.assertEqual(review.parse_cru(cru(extra='<p>CRU-TS v9.99</p>'), DAY)['latest_version'], '4.10')
        self.assertEqual(review.parse_ucdp(ucdp(), DAY)['latest_version'], '26.1')
        self.assertEqual(review.parse_vdem(vdem(), DAY)['latest_version'], '16')

    def test_version_order_is_numeric(self):
        self.assertGreater(review.version_key('4.10'), review.version_key('4.9'))
        self.assertGreater(review.version_key('4.10.1'), review.version_key('4.10'))
        self.assertEqual(review.version_key('16.0'), review.version_key('16'))

    def test_cru_unannounced_or_future_higher_version_is_ambiguous(self):
        for extra in ['<p>CRU-CY v4.11 delayed</p>', '<li>25 June 2027 CRU-CY v4.11 released</li>']:
            with self.subTest(extra=extra), self.assertRaises(review.AmbiguousRelease):
                review.parse_cru(cru(extra=extra), DAY)

    def test_ucdp_requires_country_year_heading_and_matching_download(self):
        for payload in [b'<h3>UCDP Candidate version 27.0.1</h3>',
                        ucdp().replace(b'261-csv.zip', b'271-csv.zip'),
                        ucdp().replace(b'/downloads/organizedviolencecy/', b'https://example.org/downloads/organizedviolencecy/')]:
            with self.subTest(payload=payload), self.assertRaises(review.AmbiguousRelease):
                review.parse_ucdp(payload, DAY)

    def test_ucdp_conflicting_same_product_headings_are_ambiguous(self):
        with self.assertRaises(review.AmbiguousRelease):
            review.parse_ucdp(ucdp() + ucdp('27.1'), DAY)

    def test_vdem_requires_unambiguous_core_section(self):
        for payload in [vdem(extra='<p>Version 17</p>'), vdem() + vdem(),
                        vdem().replace(b'V-Dem Core', b'V-Dem Other'),
                        vdem().replace(b'March 2026', b'March 2027')]:
            with self.subTest(payload=payload), self.assertRaises(review.AmbiguousRelease):
                review.parse_vdem(payload, DAY)

    def test_script_strings_never_become_release_evidence(self):
        fake = b'<script>25 June 2026 CRU-CY v99.99 released</script>'
        self.assertEqual(review.parse_cru(cru(extra=fake.decode()), DAY)['latest_version'], '4.10')


class MonthlyStateTests(unittest.TestCase):
    def test_second_same_month_call_never_fetches_even_if_pages_change(self):
        with tempfile.TemporaryDirectory() as folder:
            calls = []
            first = review.review_releases(folder, DAY, fetcher(PAGES, calls))
            second = review.review_releases(folder, dt.date(2026, 9, 30), fetcher({}, calls))
            self.assertEqual(len(calls), 3)
            self.assertEqual(first['status'], 'current')
            self.assertTrue(second['cached'])
            self.assertFalse(second['attention_required'])
            self.assertEqual(len(list((Path(folder)/'evidence/2026-09').glob('*.html'))), 3)

    def test_next_month_checks_once(self):
        with tempfile.TemporaryDirectory() as folder:
            calls = []
            review.review_releases(folder, DAY, fetcher(PAGES, calls))
            result = review.review_releases(folder, dt.date(2026, 10, 1), fetcher(PAGES, calls))
            self.assertEqual(len(calls), 6)
            self.assertFalse(result['cached'])
            # Cache identity follows supplied local date, not actual UTC month.
            self.assertTrue(review.review_releases(folder, '2026-10-02', fetcher({}, calls))['cached'])
            self.assertEqual(len(calls), 6)

    def test_new_same_product_release_is_review_only(self):
        with tempfile.TemporaryDirectory() as folder:
            pages = {'cru_cy': cru('4.11'), 'ucdp_annual': ucdp('27.1'), 'vdem_core': vdem('17')}
            result = review.review_releases(folder, DAY, fetcher(pages, []))
            self.assertEqual(result['status'], 'review_candidate')
            self.assertTrue(result['review_needed'])
            self.assertTrue(result['attention_required'])
            self.assertFalse(result['source_or_code_changes_made'])
            self.assertEqual(review.SOURCES['cru_cy']['adopted_version'], '4.10')

    def test_failed_and_ambiguous_checks_persist_without_daily_refetch(self):
        with tempfile.TemporaryDirectory() as folder:
            calls = []
            pages = {**PAGES, 'cru_cy': TimeoutError('source timeout'), 'vdem_core': b'<html>Sign in</html>'}
            result = review.review_releases(folder, DAY, fetcher(pages, calls))
            self.assertEqual(result['status'], 'incomplete')
            self.assertFalse(result['review_needed'])
            self.assertTrue(result['attention_required'])
            self.assertEqual([c['status'] for c in result['checks']], ['fetch_or_capture_failed', 'current', 'ambiguous'])
            review.review_releases(folder, DAY, fetcher({}, calls))
            self.assertEqual(len(calls), 3)

    def test_interrupted_attempt_cannot_start_network_again(self):
        with tempfile.TemporaryDirectory() as folder:
            calls = []
            with self.assertRaises(KeyboardInterrupt):
                review.review_releases(folder, DAY, fetcher({**PAGES, 'cru_cy': KeyboardInterrupt()}, calls))
            result = review.review_releases(folder, DAY, fetcher({}, calls))
            self.assertEqual(result['status'], 'incomplete')
            self.assertTrue(result['attention_required'])
            self.assertEqual(len(calls), 1)

    def test_concurrent_attempt_is_pending_without_network(self):
        with tempfile.TemporaryDirectory() as folder:
            calls = []
            with (Path(folder)/'.lock').open('w') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                result = review.review_releases(folder, DAY, fetcher({}, calls))
            self.assertEqual(result['status'], 'pending')
            self.assertFalse(result['attention_required'])
            self.assertFalse(calls)

    def test_invalid_cache_never_refetches(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'2026-09.json'
            path.write_text('{truncated')
            calls = []
            result = review.review_releases(folder, DAY, fetcher({}, calls))
            self.assertTrue(result['attention_required'])
            self.assertFalse(calls)

    def test_changed_adopted_version_or_false_status_in_cache_is_rejected(self):
        for field, value in [('adopted_version', '4.09'), ('status', 'newer_release_review_candidate')]:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as folder:
                result = review.review_releases(folder, DAY, fetcher(PAGES, []))
                result['checks'][0][field] = value
                (Path(folder)/'2026-09.json').write_text(json.dumps(result))
                calls = []
                checked = review.review_releases(folder, DAY, fetcher({}, calls))
                self.assertTrue(checked['attention_required'])
                self.assertFalse(calls)

    def test_seed_reuses_completed_september_review(self):
        with tempfile.TemporaryDirectory() as folder:
            seed = Path(review.__file__).with_name('release_review_seed_2026-09.json')
            (Path(folder)/'2026-09.json').write_bytes(seed.read_bytes())
            calls = []
            result = review.review_releases(folder, DAY, fetcher({}, calls))
            self.assertEqual(result['status'], 'current')
            self.assertTrue(result['cached'])
            self.assertFalse(result['attention_required'])
            self.assertFalse(calls)


if __name__ == '__main__':
    unittest.main()
