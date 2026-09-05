"""Fetch complete paginated NGDC quake/volcano snapshots with explicit scope.

Missing totals, repeated IDs, changed totals, and premature empty pages are
errors. An empty or failed catalogue is never a successful refresh. Both remote
catalogues are fetched and validated before any local catalogue replacement.
"""
from __future__ import annotations
import argparse
import csv
from datetime import datetime
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from fetch_guard import guard_or_exit
from source_tracking import write_json_if_changed

EARTHQUAKE_URL = 'https://www.ngdc.noaa.gov/hazel/hazard-service/api/v1/earthquakes'
VOLCANO_EVENTS_URL = 'https://www.ngdc.noaa.gov/hazel/hazard-service/api/v1/volcanoes'
CATALOGUES = (
    (EARTHQUAKE_URL,'noaa_significant_earthquakes.csv',-2150,
     ('year','eqMagnitude','latitude','longitude')),
    (VOLCANO_EVENTS_URL,'noaa_volcanic_events.csv',-4360,('year','name')),
)


def current_year() -> int:
    return datetime.now(ZoneInfo('America/Chicago')).year


def _total(value) -> int:
    if isinstance(value,bool) or value is None:
        raise ValueError('NGDC totalItems must be a nonnegative integer')
    try:
        count=int(value)
    except (ValueError,TypeError,OverflowError):
        raise ValueError('NGDC totalItems must be a nonnegative integer') from None
    if count < 0 or str(value) != str(count):
        raise ValueError('NGDC totalItems must be a nonnegative integer')
    return count


def fetch_all(url: str, params: dict | None = None, page_size: int = 200) -> list[dict]:
    """Require complete, internally consistent pages; reject silent truncation."""
    if not isinstance(page_size,int) or page_size <= 0:
        raise ValueError('page_size must be positive')
    query=dict(params or {},page=1,itemsPerPage=page_size)
    all_items,seen=[],set()
    expected=None
    while True:
        response=requests.get(url,params=dict(query),timeout=60,
                              headers={'User-Agent':'correlations-data-refresh/2.0'})
        response.raise_for_status()
        data=response.json()
        if not isinstance(data,dict) or not isinstance(data.get('items'),list):
            raise ValueError('NGDC response missing items array; refusing partial refresh')
        total=_total(data.get('totalItems'))
        if expected is None:
            expected=total
        elif total != expected:
            raise ValueError('NGDC totalItems changed during pagination; retry a consistent snapshot')
        items=data['items']
        if not items and len(all_items) != expected:
            raise ValueError(f'NGDC pagination ended early: {len(all_items)} of {expected} records')
        for item in items:
            if not isinstance(item,dict) or item.get('id') is None:
                raise ValueError('NGDC event missing stable source ID')
            identity=str(item['id'])
            if identity in seen:
                raise ValueError(f'NGDC duplicate source ID across pages: {identity}')
            seen.add(identity)
            all_items.append(item)
        if len(all_items)>expected:
            raise ValueError('NGDC returned more records than totalItems')
        print(f'  page {query["page"]}: +{len(items)} ({len(all_items)} / {expected})',flush=True)
        if len(all_items)==expected:
            return all_items
        query['page']+=1
        time.sleep(0.5)


def validate_catalogue(items, required, min_year, max_year):
    if not items:
        raise ValueError('NGDC returned an empty catalogue; retaining existing snapshot')
    keys=set().union(*(item.keys() for item in items))
    missing=set(required)-keys
    if missing:
        raise ValueError(f'NGDC catalogue missing required columns: {sorted(missing)}')
    for item in items:
        value=item.get('year')
        if isinstance(value,bool):
            raise ValueError('NGDC year must be an integer')
        try:
            year=int(value)
        except (ValueError,TypeError,OverflowError):
            raise ValueError('NGDC record has invalid year') from None
        if str(year) != str(value) or not min_year <= year <= max_year:
            raise ValueError(f'NGDC record lies outside declared year scope: {value}')


def write_guarded(items: list[dict], destination: Path, required: tuple[str,...]):
    keys=list(dict.fromkeys(key for item in items for key in item))
    temporary=destination.with_name('_'+destination.name+'.tmp')
    with temporary.open('w',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=keys)
        writer.writeheader();writer.writerows(items)
    guard_or_exit(temporary,destination,required_cols=list(required))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path,default=Path('data'))
    parser.add_argument('--max-year',type=int,default=None)
    args=parser.parse_args(argv)
    year_now=current_year()
    max_year=year_now if args.max_year is None else args.max_year
    if max_year > year_now:
        parser.error('--max-year cannot exceed current calendar year')
    args.data_dir.mkdir(parents=True,exist_ok=True)
    staged=[]
    for url,name,min_year,required in CATALOGUES:
        if max_year < min_year:
            parser.error('--max-year precedes catalogue start')
        print(f'Fetching {name}: declared query years {min_year} through {max_year}')
        items=fetch_all(url,{'minYear':min_year,'maxYear':max_year})
        validate_catalogue(items,required,min_year,max_year)
        staged.append((url,name,min_year,required,items))
    for url,name,min_year,required,items in staged:
        write_guarded(items,args.data_dir/name,required)
        write_json_if_changed(Path(str(args.data_dir/name)+'.coverage.json'),{
            'schema_version':1,'start_year':min_year,'end_year':max_year,
            'complete_through_year':min(max_year,year_now-1),'gap_years':[],
            'completeness':'source_defined_catalog','source_url':url,
            'source_version':'NGDC live paginated API',
            'notes':'Successful query bounds, independent of last qualifying event. Historical reporting is selective; source scope does not imply complete detection.'})
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
