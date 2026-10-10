#!/usr/bin/env python3
"""Experimental job-link discovery via Bing public RSS results.
Does not crawl employer/job-board pages. It merges discovered direct offer URLs
with the existing JSON, classifies by title, and preserves prior records when
RSS returns no usable results. No guarantee of completeness or freshness.
"""
from __future__ import annotations
import json, os, re, sys, time
from datetime import datetime, timezone, timedelta
from urllib.parse import quote, urlparse, parse_qs, unquote
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JOBS_PATH = os.path.join(ROOT, "jobs.json")
USER_AGENT = "EmpleosPeruTech-JobDiscovery/2.0 (public RSS search; does not crawl job-board pages)"
QUERIES = [
    ("Administración", 'site:pe.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo empleo administración Perú'),
    ("Atención al cliente", 'site:pe.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo atención al cliente Perú'),
    ("Ventas", 'site:pe.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo asesor ventas vendedor Perú'),
    ("Producción", 'site:pe.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo producción operario Perú'),
    ("Almacén y logística", 'site:pe.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo almacén logística auxiliar Perú'),
    ("Construcción", 'site:pe.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo construcción técnico obra Perú'),
    ("Diseño y marketing", 'site:pe.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo diseñador marketing Perú'),
    ("Informática", 'site:pe.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo sistemas informática soporte técnico Perú'),
    ("Trabajo remoto", 'site:pe.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo trabajo remoto teletrabajo Perú'),
    ("Sin experiencia", 'site:pe.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo sin experiencia primer empleo Perú'),
    ("Prácticas", 'site:pe.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo practicante prácticas preprofesionales Perú'),
    ("Empleo general", 'site:pe.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo empleo Lima Perú'),
]


def bing_rss(query: str) -> bytes:
    url = "https://www.bing.com/search?format=rss&q=" + quote(query)
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml,application/xml,text/xml"})
    with urlopen(req, timeout=25) as response:
        return response.read()


def unwrap_url(raw: str) -> str:
    try:
        params = parse_qs(urlparse(raw).query)
        for key in ("url", "u", "target"):
            if key in params:
                candidate = unquote(params[key][0])
                if candidate.startswith("http"):
                    return candidate
    except Exception:
        pass
    return raw


def clean_title(title: str) -> str:
    title = re.sub(r"\s+[-|–—]\s+Computrabajo.*$", "", title, flags=re.I)
    return re.sub(r"\s+", " ", title).strip()[:180]


def category_for(title: str, query_category: str) -> str:
    t = title.casefold()
    rules = [
        ("Trabajo remoto", ("remoto", "remota", "teletrabajo", "desde casa")),
        ("Atención al cliente", ("atención al cliente", "call center", "servicio al cliente", "customer")),
        ("Ventas", ("ventas", "vendedor", "asesor comercial", "comercial")),
        ("Administración", ("administrativo", "administrativa", "asistente", "secretaria", "contable")),
        ("Producción", ("producción", "operario", "ensamble", "manufactura")),
        ("Almacén y logística", ("almacén", "almacen", "logística", "logistica", "despacho", "inventario")),
        ("Construcción", ("construcción", "construccion", "obra", "electricista", "gasfitero")),
        ("Diseño y marketing", ("diseñador", "diseñadora", "diseño", "marketing", "community manager")),
        ("Informática", ("sistemas", "informática", "informatica", "soporte técnico", "programador", "desarrollador")),
        ("Prácticas", ("practicante", "prácticas", "practicas", "preprofesional")),
    ]
    for category, terms in rules:
        if any(term in t for term in terms):
            return category
    return query_category


def valid_offer_url(link: str) -> bool:
    parsed = urlparse(link)
    host = (parsed.hostname or "").lower()
    path = parsed.path.lower()
    return host in {"pe.computrabajo.com", "www.computrabajo.com"} and "/ofertas-de-trabajo/oferta-de-trabajo-" in path


def main() -> int:
    try:
        with open(JOBS_PATH, encoding="utf-8") as f:
            old_data = json.load(f)
    except Exception:
        old_data = {"updated": None, "jobs": []}
    old_jobs = old_data.get("jobs", []) if isinstance(old_data.get("jobs", []), list) else []
    merged: dict[str, dict] = {}
    for job in old_jobs:
        if isinstance(job, dict) and job.get("url"):
            merged[str(job["url"])] = job

    found_count = 0
    failures = 0
    today = datetime.now(timezone.utc).date().isoformat()
    for query_category, query in QUERIES:
        try:
            root = ET.fromstring(bing_rss(query))
            for item in root.findall(".//item"):
                title_el, link_el = item.find("title"), item.find("link")
                if title_el is None or link_el is None or not title_el.text or not link_el.text:
                    continue
                link = unwrap_url(link_el.text.strip())
                if not valid_offer_url(link):
                    continue
                title = clean_title(title_el.text)
                if not title:
                    continue
                previous = merged.get(link, {})
                merged[link] = {
                    **previous,
                    "title": title,
                    "company": previous.get("company", "Consulta la empresa en el anuncio"),
                    "location": previous.get("location", "Perú · Ver anuncio"),
                    "mode": previous.get("mode", "Por confirmar"),
                    "category": category_for(title, query_category),
                    "source": "Computrabajo · resultado de búsqueda",
                    "extra": previous.get("extra", "Verificar vigencia"),
                    "description": previous.get("description", "Enlace descubierto mediante resultados públicos de búsqueda. Confirma empresa, ubicación, sueldo, requisitos y vigencia en el anuncio original."),
                    "url": link,
                    "discoveredAt": previous.get("discoveredAt", today),
                    "lastSeen": today,
                    "externalDiscovery": True,
                }
                found_count += 1
        except Exception as exc:
            failures += 1
            print(f"RSS query failed ({query_category}): {exc}", file=sys.stderr)
        time.sleep(1)

    # Keep curated/manual listings. Expire only automatically discovered links not seen in 45 days.
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=45)).isoformat()
    kept = []
    for job in merged.values():
        if job.get("externalDiscovery"):
            last_seen = str(job.get("lastSeen") or job.get("discoveredAt") or "")
            if last_seen and last_seen < cutoff:
                continue
        kept.append(job)
    kept.sort(key=lambda j: (str(j.get("category", "")).casefold(), str(j.get("title", "")).casefold()))
    status = f"Búsqueda experimental completada. Enlaces procesados: {found_count}; consultas RSS fallidas: {failures}."
    data = {
        "updated": today,
        "jobs": kept,
        "note": status,
        "source": "Resultados RSS públicos de Bing; no se rastrean directamente las páginas de Computrabajo.",
        "searchFailures": failures,
    }
    with open(JOBS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"Ofertas guardadas: {len(kept)}; enlaces procesados hoy: {found_count}; consultas fallidas: {failures}")
    if found_count == 0:
        print("Aviso: no se descubrieron enlaces directos nuevos en esta ejecución; se conservaron ofertas anteriores.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
