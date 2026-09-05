"""Regional selected-drought affected-population spectra; no solar attribution."""
import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from catalog_coverage import apply_coverage
from correlate_events import _allocate
from periodogram_extended import spectral_inference
from statistical_helpers import bh_adjust,contiguous_overlap,last_complete_year

REGIONS={
    'Africa (Sahel + East)':['Africa','Horn of Africa'],
    'North America (incl Mexico)':['North America','Central America','Mesoamerica'],
    'South Asia':['South Asia'], 'East Asia':['East Asia'],
    'Europe':['Western Europe','Europe','Eastern Europe','Northern Europe'],
    'Russia / Central Asia':['Russia','Central Asia'], 'South America':['South America'],
    'Middle East / Levant':['Levant','Middle East','Israel/Phoenicia','Eastern Mediterranean'],
}


def regional_series(frame,path,lo=1900,hi=None):
    hi=last_complete_year() if hi is None else hi
    # Original event duration; unknown affected populations stay unknown.
    s=_allocate(frame,'people_affected',lo,hi)
    return np.log10(apply_coverage(s,path,'droughts.csv')+1)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--droughts-csv',default='data/droughts.csv')
    ap.add_argument('--n-boot',type=int,default=10000)
    ap.add_argument('--out',default='figures');args=ap.parse_args()
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    df=pd.read_csv(args.droughts_csv);rows=[]
    for region,members in REGIONS.items():
        sub=df[df.region.isin(members)]
        row=dict(region=region,n_events=len(sub),n_years=0,band_p=np.nan,peak_period=np.nan,
                 peak_ratio=np.nan,status='insufficient selected events')
        if len(sub)>=5:
            try:
                finite=contiguous_overlap({'affected':regional_series(sub,args.droughts_csv)},min_years=40)
                if finite.affected.gt(0).sum()<5:raise ValueError('Fewer than five nonzero annual allocations')
                result=spectral_inference(finite.affected.to_numpy(),n_boot=args.n_boot)
                row.update(n_years=len(finite),start_year=int(finite.index.min()),end_year=int(finite.index.max()),
                           status='exploratory',**{k:result[k] for k in ['band_p','peak_period','peak_ratio']})
            except ValueError as error:row['status']=str(error)
        rows.append(row)
    results=pd.DataFrame(rows);results['q_band_family']=bh_adjust(results.band_p)
    results.to_csv(out/'29_regional_drought_results.csv',index=False)
    fig,ax=plt.subplots(figsize=(12,6))
    for i,row in results.iterrows():
        if row.status=='exploratory':
            ax.barh(i,row.peak_ratio,color='#bd5944' if row.q_band_family<.05 else '#648d9b')
            ax.text(row.peak_ratio+.1,i,f'{row.peak_period:.1f}y; q={row.q_band_family:.3f}',va='center',fontsize=9)
        else:ax.text(.05,i,'Unavailable: '+row.status,va='center',fontsize=9)
    ax.set_yticks(range(len(results)),results.region);ax.invert_yaxis()
    finite=results.peak_ratio.dropna()
    ax.set_xlim(0,max(5,finite.max()*1.4 if len(finite) else 5))
    ax.set_xlabel('9–13-year maximum / mean AR(1) surrogate power; band search + eight-region BH')
    ax.set_title('Regional drought affected-population allocation proxies\nSelected catalog; human impacts ≠ physical drought severity or solar attribution')
    fig.tight_layout();fig.savefig(out/'29_regional_drought_periodograms.png',dpi=120);plt.close(fig)
    print(results.to_string(index=False))

if __name__=='__main__':main()
