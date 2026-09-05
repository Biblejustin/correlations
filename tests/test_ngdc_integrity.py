"""NGDC incomplete pagination must fail before a known-good CSV is replaced."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import fetch_ngdc as n


def response(body):
    return Mock(json=Mock(return_value=body),raise_for_status=Mock())


class NgdcIntegrityTests(unittest.TestCase):
    def fetch(self,bodies):
        with patch.object(n.requests,'get',side_effect=[response(b) for b in bodies]),patch.object(n.time,'sleep'):
            return n.fetch_all('https://example.invalid/catalogue',page_size=2)

    def test_full_pagination_returns_each_unique_record(self):
        result=self.fetch([{'totalItems':3,'items':[{'id':1},{'id':2}]},
                           {'totalItems':3,'items':[{'id':3}]}])
        self.assertEqual([r['id'] for r in result],[1,2,3])

    def test_premature_empty_page_is_error(self):
        with self.assertRaisesRegex(ValueError,'ended early'):
            self.fetch([{'totalItems':3,'items':[{'id':1},{'id':2}]},
                        {'totalItems':3,'items':[]}])

    def test_missing_or_error_total_never_means_one_page_complete(self):
        for body in [{'items':[{'id':1}]},{'error':'unavailable'},
                     {'items':[],'totalItems':None},{'items':[],'totalItems':-1}]:
            with self.subTest(body=body),self.assertRaises(ValueError):
                self.fetch([body])

    def test_repeated_page_and_changed_total_rejected(self):
        for second in [{'totalItems':3,'items':[{'id':1}]},
                       {'totalItems':4,'items':[{'id':3}]}]:
            with self.subTest(second=second),self.assertRaises(ValueError):
                self.fetch([{'totalItems':3,'items':[{'id':1},{'id':2}]},second])

    def test_valid_empty_query_distinct_from_refresh_success(self):
        self.assertEqual(self.fetch([{'totalItems':0,'items':[]}]),[])
        with self.assertRaisesRegex(ValueError,'empty catalogue'):
            n.validate_catalogue([],('year',),1900,2026)
        with self.assertRaises(ValueError):
            self.fetch([{'totalItems':0,'items':[{'id':1}]}])

    def test_record_missing_identity_or_outside_scope_rejected(self):
        with self.assertRaisesRegex(ValueError,'stable source ID'):
            self.fetch([{'totalItems':1,'items':[{'year':2020}]}])
        with self.assertRaisesRegex(ValueError,'outside declared'):
            n.validate_catalogue([{'id':1,'year':2027}],('year',),1900,2026)

    def test_dynamic_year_and_second_fetch_failure_preserve_both_catalogues(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for _,name,_,_ in n.CATALOGUES:(root/name).write_text('known-good\n')
            quake={'id':1,'year':2031,'eqMagnitude':7,'latitude':1,'longitude':2}
            with patch.object(n,'current_year',return_value=2031), \
                 patch.object(n,'fetch_all',side_effect=[[quake],ValueError('short volcano page')]) as fetch:
                with self.assertRaises(ValueError):n.main(['--data-dir',tmp])
            self.assertEqual(fetch.call_args_list[0].args[1]['maxYear'],2031)
            for _,name,_,_ in n.CATALOGUES:self.assertEqual((root/name).read_text(),'known-good\n')


if __name__=='__main__':unittest.main()
