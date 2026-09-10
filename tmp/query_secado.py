import sqlite3,json,csv
from pathlib import Path
db=sqlite3.connect(':memory:'); db.row_factory=sqlite3.Row
db.execute('CREATE TABLE controlador (fecha TEXT, awm TEXT, temperatura TEXT, consigna TEXT, ciclo TEXT)')
rows=json.loads(Path('tmp/process_rows.json').read_text())
db.executemany('INSERT INTO controlador VALUES (?,?,?,?,?)',[(r['time'],r['raw'][0],r['raw'][2],r['raw'][4],'3367') for r in rows])
rr=list(csv.reader(Path('Informe_Camara3_Ciclo_3367.csv').read_text(encoding='cp1252').splitlines(),delimiter=';'))
r=next(x for x in rr if x and x[0]=='3367')
num=lambda s: float(s.strip().replace('%','').replace(',','.'))
fields={x[0].strip().rstrip(':'):x[1].strip() for x in rr if len(x)>1}
db.execute('CREATE TABLE humedad(ciclo TEXT, muestras INT, media REAL, desviacion REAL, maximo REAL, minimo REAL, bajas REAL, altas REAL, rango REAL, meta REAL)')
db.execute('INSERT INTO humedad VALUES (?,?,?,?,?,?,?,?,?,?)',(r[0],int(r[1]),num(r[3]),num(r[4]),num(r[5]),num(r[6]),num(fields['Bajas']),num(fields['Altas']),num(fields['Rango']),num(fields['Aprueba'])))
queries={
'humedad': '''SELECT ciclo, muestras, media / 100.0 AS media, desviacion, maximo, minimo, rango / 100.0 AS cumplimiento, meta / 100.0 AS meta FROM humedad WHERE ciclo = '3367';''',
'calidad': '''SELECT ciclo, muestras AS total_muestras, 'Bajas (<7 %)' AS categoria, bajas AS porcentaje, ROUND(muestras*bajas/100.0) AS muestras_estimadas FROM humedad UNION ALL SELECT ciclo, muestras, 'En rango (7–11 %)', rango, ROUND(muestras*rango/100.0) FROM humedad UNION ALL SELECT ciclo, muestras, 'Altas (>11 %)', altas, ROUND(muestras*altas/100.0) FROM humedad;''',
'programa': '''SELECT substr(fecha,1,13)||':00:00' AS hora, ciclo, ROUND(AVG(CAST(REPLACE(awm,',','.') AS REAL)),2) AS awm_aprox, ROUND(AVG(CAST(REPLACE(temperatura,',','.') AS REAL)),2) AS temp_aprox, ROUND(AVG(CAST(REPLACE(consigna,',','.') AS REAL)),2) AS consigna_aprox, COUNT(*) AS registros FROM controlador WHERE ciclo = '3367' GROUP BY substr(fecha,1,13), ciclo ORDER BY hora;''',
'duracion': '''SELECT (unixepoch(MAX(fecha))-unixepoch(MIN(fecha)))/3600.0 AS duracion FROM controlador WHERE ciclo = '3367';'''
}
datasets={k:[dict(r) for r in db.execute(q)] for k,q in queries.items()}
Path('tmp/reviewed_queries.json').write_text(json.dumps({'queries':queries,'datasets':datasets},ensure_ascii=False),encoding='utf-8')
print(json.dumps({'summary':datasets['humedad'],'duracion':datasets['duracion'],'counts':{k:len(v) for k,v in datasets.items()}},ensure_ascii=False))
