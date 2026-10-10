#!/usr/bin/env python3
"""Import job listings through Jooble's official REST API.

Uses a small rotating set of targeted searches on each daily run so the site
can collect more relevant jobs without burning the API quota too quickly.
Requires JOOBLE_API_KEY in the environment.
"""
import json, os, sys, urllib.request, urllib.error
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JOBS_FILE = ROOT / 'jobs.json'
API_KEY = os.environ.get('JOOBLE_API_KEY', '').strip()
ENDPOINT = 'https://pe.jooble.org/api/'
RESULTS_PER_QUERY = 50
MAX_SAVED = 200

# Four queries per run = up to 200 results. The groups rotate by weekday so
# the free API quota is distributed across different job categories.
QUERY_GROUPS = [
    [
        ('administración', 'Administración'),
        ('ventas', 'Ventas'),
        ('atención al cliente', 'Atención al cliente'),
        ('contabilidad', 'Contabilidad'),
    ],
    [
        ('informática', 'Informática'),
        ('programador', 'Informática'),
        ('marketing', 'Diseño y marketing'),
        ('diseñador', 'Diseño y marketing'),
    ],
    [
        ('construcción', 'Construcción'),
        ('logística', 'Almacén y logística'),
        ('almacén', 'Almacén y logística'),
        ('producción', 'Producción'),
    ],
    [
        ('salud', 'Salud'),
        ('enfermería', 'Salud'),
        ('educación', 'Educación'),
        ('docente', 'Educación'),
    ],
    [
        ('empleo remoto', 'Trabajo remoto'),
        ('trabajo remoto', 'Trabajo remoto'),
        ('practicante', 'Prácticas'),
        ('prácticas', 'Prácticas'),
    ],
    [
        ('Lima', 'Empleo general'),
        ('Callao', 'Empleo general'),
        ('Huaraz', 'Empleo general'),
        ('Arequipa', 'Empleo general'),
    ],
    [
        ('ingeniero', 'Ingeniería'),
        ('ingeniería', 'Ingeniería'),
        ('recursos humanos', 'Recursos humanos'),
        ('compras', 'Compras'),
    ],
]

if not API_KEY:
    print('ERROR: falta el secreto JOOBLE_API_KEY. Solicita la clave en https://pe.jooble.org/api/about y guárdala en GitHub Secrets.')
    sys.exit(2)

# Rotate groups by day of month. This avoids repeating the same four queries
# every day while still refreshing the whole portal over time.
day_number = datetime.now(timezone.utc).day
group_index = (day_number - 1) % len(QUERY_GROUPS)
queries = QUERY_GROUPS[group_index]


def classify(title: str, fallback: str) -> str:
    title_l = title.casefold()
    rules = [
        ('Atención al cliente', ('atención al cliente', 'call center', 'servicio al cliente', 'teleoperador')),
        ('Ventas', ('ventas', 'vendedor', 'asesor comercial', 'ejecutivo comercial', 'promotor')),
        ('Administración', ('administrativo', 'administrativa', 'asistente', 'secretaria', 'recepcionista')),
        ('Contabilidad', ('contabilidad', 'contador', 'contable', 'finanzas')),
        ('Producción', ('producción', 'produccion', 'operario', 'ensamble', 'manufactura')),
        ('Almacén y logística', ('almacén', 'almacen', 'logística', 'logistica', 'despacho', 'inventario')),
        ('Construcción', ('construcción', 'construccion', 'obra', 'electricista', 'gasfitero', 'soldador')),
        ('Diseño y marketing', ('diseñador', 'diseñadora', 'diseño', 'marketing', 'community manager', 'publicidad')),
        ('Informática', ('sistemas', 'informática', 'informatica', 'soporte técnico', 'soporte tecnico', 'programador', 'desarrollador', 'software')),
        ('Trabajo remoto', ('remoto', 'remota', 'teletrabajo', 'desde casa', 'home office')),
        ('Prácticas', ('practicante', 'prácticas', 'practicas', 'preprofesional')),
        ('Salud', ('salud', 'enfermería', 'enfermeria', 'médico', 'medico', 'odontología', 'farmacia')),
        ('Educación', ('educación', 'educacion', 'docente', 'profesor', 'maestro', 'tutor')),
        ('Ingeniería', ('ingeniero', 'ingeniería', 'ingenieria')),
        ('Recursos humanos', ('recursos humanos', 'rrhh', 'selección de personal')),
        ('Compras', ('compras', 'procurement', 'abastecimiento')),
    ]
    for category, terms in rules:
        if any(term in title_l for term in terms):
            return category
    return fallback or 'Empleo general'


def fetch(query: str):
    payload = {
        'keywords': query,
        'location': 'Perú',
        'page': '1',
        'ResultOnPage': RESULTS_PER_QUERY,
        'companysearch': False,
    }
    request = urllib.request.Request(
        ENDPOINT + API_KEY,
        data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        headers={
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'EmpleosPeru.tech/1.1',
        },
        method='POST',
    )
    with urllib.request.urlopen(request, timeout=35) as response:
        return json.loads(response.read().decode('utf-8'))


new_jobs = []
seen_urls = set()
total_matches = 0
successful_queries = 0

for query, fallback_category in queries:
    try:
        result = fetch(query)
        successful_queries += 1
        total_matches += int(result.get('totalCount') or 0)
        jobs = result.get('jobs', []) or []
        print(f'Consulta "{query}": {result.get("totalCount", 0)} coincidencias; {len(jobs)} resultados.')
        for raw in jobs:
            link = (raw.get('link') or '').strip()
            title = (raw.get('title') or '').strip()
            if not link.startswith('http') or not title or link in seen_urls:
                continue
            seen_urls.add(link)
            loc = (raw.get('location') or 'Perú').strip()
            new_jobs.append({
                'title': title,
                'company': (raw.get('company') or 'Empresa por confirmar').strip(),
                'location': loc,
                'mode': (raw.get('type') or 'Ver modalidad').strip(),
                'category': classify(title, fallback_category),
                'source': (raw.get('source') or 'Jooble').strip(),
                'extra': f'Actualización de Jooble · búsqueda: {query}',
                'salary': (raw.get('salary') or '').strip(),
                'description': (raw.get('snippet') or 'Consulta los requisitos y condiciones en la publicación original.').strip(),
                'url': link,
                'externalDiscovery': True,
                'updatedSource': raw.get('updated', ''),
            })
    except urllib.error.HTTPError as e:
        detail = e.read().decode('utf-8', 'replace')[:500]
        print(f'ERROR Jooble API en "{query}" HTTP {e.code}: {detail}')
    except Exception as e:
        print(f'ERROR consultando Jooble en "{query}": {e}')

if not successful_queries:
    print('ERROR: ninguna consulta a Jooble respondió correctamente.')
    sys.exit(1)

# Preserve existing offers and replace duplicates with the fresher API copy.
try:
    old = json.loads(JOBS_FILE.read_text(encoding='utf-8'))
    old_jobs = old.get('jobs', []) if isinstance(old.get('jobs', []), list) else []
except Exception:
    old_jobs = []

merged = {}
for job in old_jobs:
    if isinstance(job, dict) and (job.get('url') or job.get('link')):
        merged[job.get('url') or job.get('link')] = job
for job in new_jobs:
    merged[job['url']] = job

jobs = list(merged.values())
api_urls = {job['url'] for job in new_jobs}
jobs.sort(key=lambda j: (0 if (j.get('url') or j.get('link')) in api_urls else 1, str(j.get('title', '')).casefold()))
jobs = jobs[:MAX_SAVED]

today = datetime.now(timezone.utc).date().isoformat()
data = {
    'updated': today,
    'jobs': jobs,
    'note': f'Jooble API: {len(new_jobs)} resultados únicos recibidos en {successful_queries} consultas; {len(jobs)} ofertas disponibles en total.',
    'source': 'Jooble REST API oficial; los anuncios pertenecen a sus fuentes originales.',
    'totalCount': total_matches,
    'apiResults': len(new_jobs),
    'queries': [q for q, _ in queries],
}
JOBS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(f'Grupo {group_index + 1}/{len(QUERY_GROUPS)} completado: {len(new_jobs)} resultados únicos; {len(jobs)} ofertas guardadas.')
print(f'Coincidencias informadas por Jooble en este grupo: {total_matches}.')
