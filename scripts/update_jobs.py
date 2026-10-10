#!/usr/bin/env python3
"""Import job listings through Jooble's official REST API.
Requires JOOBLE_API_KEY in the environment. Uses one API request per run to
conserve the documented free lifetime quota. Does not scrape job boards.
"""
import json, os, sys, urllib.request, urllib.error
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
JOBS_FILE=ROOT/'jobs.json'
API_KEY=os.environ.get('JOOBLE_API_KEY','').strip()
ENDPOINT='https://pe.jooble.org/api/'

if not API_KEY:
    print('ERROR: falta el secreto JOOBLE_API_KEY. Solicita la clave en https://pe.jooble.org/api/about y guárdala en GitHub Secrets.')
    sys.exit(2)

payload={
    'keywords':'empleo',
    'location':'Perú',
    'page':'1',
    'ResultOnPage':50,
    'companysearch':False
}
request=urllib.request.Request(
    ENDPOINT+API_KEY,
    data=json.dumps(payload,ensure_ascii=False).encode('utf-8'),
    headers={'Content-Type':'application/json','Accept':'application/json','User-Agent':'EmpleosPeru.tech/1.0'},
    method='POST'
)
try:
    with urllib.request.urlopen(request,timeout=35) as response:
        result=json.loads(response.read().decode('utf-8'))
except urllib.error.HTTPError as e:
    detail=e.read().decode('utf-8','replace')[:500]
    print(f'ERROR Jooble API HTTP {e.code}: {detail}')
    sys.exit(1)
except Exception as e:
    print(f'ERROR consultando Jooble API: {e}')
    sys.exit(1)

new_jobs=[]
for raw in result.get('jobs',[]):
    link=(raw.get('link') or '').strip()
    title=(raw.get('title') or '').strip()
    if not link.startswith('http') or not title:
        continue
    title_l=title.casefold()
    category='Empleo general'
    rules=[
        ('Atención al cliente',('atención al cliente','call center','servicio al cliente')),
        ('Ventas',('ventas','vendedor','asesor comercial','ejecutivo comercial')),
        ('Administración',('administrativo','administrativa','asistente','secretaria','contable')),
        ('Producción',('producción','operario','ensamble','manufactura')),
        ('Almacén y logística',('almacén','almacen','logística','logistica','despacho','inventario')),
        ('Construcción',('construcción','construccion','obra','electricista','gasfitero')),
        ('Diseño y marketing',('diseñador','diseñadora','diseño','marketing','community manager')),
        ('Informática',('sistemas','informática','informatica','soporte técnico','programador','desarrollador')),
        ('Trabajo remoto',('remoto','remota','teletrabajo','desde casa')),
        ('Prácticas',('practicante','prácticas','practicas','preprofesional')),
    ]
    for cat,terms in rules:
        if any(term in title_l for term in terms):
            category=cat; break
    loc=(raw.get('location') or 'Perú').strip()
    typ=(raw.get('type') or 'Ver modalidad').strip()
    salary=(raw.get('salary') or '').strip()
    new_jobs.append({
        'title':title,
        'company':(raw.get('company') or 'Empresa por confirmar').strip(),
        'location':loc,
        'mode':typ,
        'category':category,
        'source':(raw.get('source') or 'Jooble').strip(),
        'extra':'Actualización de Jooble',
        'salary':salary,
        'description':(raw.get('snippet') or 'Consulta los requisitos y condiciones en la publicación original.').strip(),
        'url':link,
        'externalDiscovery':True,
        'updatedSource':raw.get('updated','')
    })

# Preserve existing manually curated offers, then append fresh API results without duplicate URLs.
try:
    old=json.loads(JOBS_FILE.read_text(encoding='utf-8'))
    old_jobs=old.get('jobs',[]) if isinstance(old.get('jobs',[]),list) else []
except Exception:
    old_jobs=[]
merged={}
for job in old_jobs:
    if isinstance(job,dict) and (job.get('url') or job.get('link')):
        merged[job.get('url') or job.get('link')]=job
for job in new_jobs:
    merged[job['url']]=job
jobs=list(merged.values())
# Put fresh API results first; retain curated listings afterwards.
api_urls={job['url'] for job in new_jobs}
jobs.sort(key=lambda j: (0 if (j.get('url') or j.get('link')) in api_urls else 1, str(j.get('title','')).casefold()))
# Cap file size while prioritizing latest API results.
jobs=jobs[:100]
today=datetime.now(timezone.utc).date().isoformat()
data={
    'updated':today,
    'jobs':jobs,
    'note':f'Jooble API: {len(new_jobs)} resultados recibidos; {len(jobs)} ofertas disponibles en total.',
    'source':'Jooble REST API oficial; los anuncios pertenecen a sus fuentes originales.',
    'totalCount':result.get('totalCount',len(new_jobs)),
    'apiResults':len(new_jobs)
}
JOBS_FILE.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(f"Jooble informó {data['totalCount']} coincidencias; se recibieron {len(new_jobs)} resultados y se guardaron {len(jobs)} ofertas.")
if not new_jobs:
    print('AVISO: la API no devolvió ofertas para la consulta general. Se conservaron las ofertas anteriores.')
