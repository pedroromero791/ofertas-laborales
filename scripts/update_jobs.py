#!/usr/bin/env python3
"""Discover public Computrabajo Peru offer links through Bing's RSS search results.
Does not crawl or request Computrabajo pages directly. RSS discovery is experimental
and can return zero results; in that case the previous jobs.json is preserved.
"""
from __future__ import annotations
import json, os, re, sys, time
from datetime import datetime, timezone
from urllib.parse import quote, urlparse, parse_qs, unquote
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JOBS_PATH = os.path.join(ROOT, "jobs.json")
USER_AGENT = "EmpleosPeruTech-JobDiscovery/1.0 (public RSS search; contact site owner)"
QUERIES = [
    'site:pe.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo empleo Perú',
    'site:pe.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo empleo Lima',
    'site:pe.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo trabajo remoto Perú',
    'site:pe.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo sin experiencia Perú',
    'site:pe.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo auxiliar ventas atención cliente Perú',
]


def bing_rss(query: str) -> bytes:
    url = "https://www.bing.com/search?format=rss&q=" + quote(query)
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml,application/xml,text/xml"})
    with urlopen(req, timeout=25) as response:
        return response.read()


def unwrap_url(raw: str) -> str:
    # Search engines may wrap the result URL in a redirect query parameter.
    try:
        parsed = urlparse(raw)
        params = parse_qs(parsed.query)
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
    title = re.sub(r"\s+", " ", title).strip()
    return title[:180]


def main() -> int:
    old = {"updated": None, "jobs": []}
    if os.path.exists(JOBS_PATH):
        try:
            with open(JOBS_PATH, encoding="utf-8") as f:
                old = json.load(f)
        except Exception:
            pass

    found = {}
    failures = 0
    for query in QUERIES:
        try:
            xml = bing_rss(query)
            root = ET.fromstring(xml)
            for item in root.findall(".//item"):
                title_el = item.find("title")
                link_el = item.find("link")
                if title_el is None or link_el is None or not title_el.text or not link_el.text:
                    continue
                link = unwrap_url(link_el.text.strip())
                parsed = urlparse(link)
                host = (parsed.hostname or "").lower()
                path = parsed.path.lower()
                # Only direct offer detail pages, never search pages or arbitrary URLs.
                if host not in {"pe.computrabajo.com", "www.computrabajo.com"}:
                    continue
                if "/ofertas-de-trabajo/oferta-de-trabajo-" not in path:
                    continue
                title = clean_title(title_el.text)
                if not title:
                    continue
                found[link] = {
                    "title": title,
                    "company": "Consulta la empresa en el anuncio",
                    "location": "Perú · Ver anuncio",
                    "mode": "Por confirmar",
                    "category": "Oferta externa",
                    "source": "Computrabajo · resultado de búsqueda",
                    "extra": "Verificar vigencia",
                    "description": "Vacante descubierta mediante resultados públicos de búsqueda. Confirma empresa, ubicación, sueldo, requisitos y vigencia en la publicación original.",
                    "url": link,
                    "discoveredAt": datetime.now(timezone.utc).date().isoformat(),
                }
        except Exception as exc:
            failures += 1
            print(f"RSS query failed: {query!r}: {exc}", file=sys.stderr)
        time.sleep(1)

    # If search did not return usable direct offer links, preserve the last known list.
    if found:
        jobs = sorted(found.values(), key=lambda x: x["title"].lower())
        status = "RSS search completed; links discovered from public search results."
    else:
        jobs = old.get("jobs", []) if isinstance(old.get("jobs", []), list) else []
        status = "No new direct offer links were found; previous data preserved."
        print(status, file=sys.stderr)

    data = {
        "updated": datetime.now(timezone.utc).date().isoformat(),
        "jobs": jobs,
        "note": status,
        "source": "Bing RSS search results; no direct crawling of Computrabajo pages.",
        "searchFailures": failures,
    }
    with open(JOBS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"Saved {len(jobs)} offers; RSS query failures: {failures}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
