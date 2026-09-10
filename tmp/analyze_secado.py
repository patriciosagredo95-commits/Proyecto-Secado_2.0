from pypdf import PdfReader
from datetime import datetime
from collections import Counter, defaultdict
import json,re
from pathlib import Path
p=PdfReader('archive_Camara Secado 3_20260824T171619.process_984-normal.pdf')
rows=[]
for page in p.pages[2:]:
    for line in page.extract_text().splitlines():
        m=re.match(r'^(\d{2}-\d{2}-\d{4} \d{1,2}:\d{2}:\d{2}) (.*)$',line)
        if m:
            vals=m[2].split()
            rows.append({'time':datetime.strptime(m[1],'%d-%m-%Y %H:%M:%S').isoformat(),'raw':vals})
Path('tmp/process_rows.json').write_text(json.dumps(rows),encoding='utf-8')
print('rows',len(rows),'lengths',Counter(len(r['raw']) for r in rows))
print('first,last',rows[0],rows[-1])
gaps=Counter((datetime.fromisoformat(b['time'])-datetime.fromisoformat(a['time'])).total_seconds() for a,b in zip(rows,rows[1:]))
print('gaps_seconds',gaps)
hourly=defaultdict(list)
for r in rows: hourly[r['time'][:13]].append(r)
out=[]
for hour, rr in hourly.items():
    out.append({'hora':hour+':00:00','awm_aprox':round(sum(float(r['raw'][0].replace(',','.')) for r in rr)/len(rr),2),'temp_aprox':round(sum(float(r['raw'][2].replace(',','.')) for r in rr)/len(rr),2),'consigna_aprox':round(sum(float(r['raw'][4].replace(',','.')) for r in rr)/len(rr),2),'registros':len(rr),'ciclo':'3367'})
Path('tmp/hourly.json').write_text(json.dumps(out),encoding='utf-8')
print('daily endpoints',[(h,rr[0]['raw'][:6],rr[-1]['raw'][:6]) for h,rr in hourly.items() if h.endswith('T12')])
for i in range(16):
    vals=[float(r['raw'][i].replace(',','.')) for r in rows if len(r['raw'])==16]
    print('col',i,'min',min(vals),'max',max(vals),'zeros',sum(v==0 for v in vals))
for s,e in [('2026-08-24T17:16:57','2026-09-01T05:42:36'),('2026-08-26T08:12:11','2026-09-01T09:26:22')]:print('duration',str(datetime.fromisoformat(e)-datetime.fromisoformat(s)))
