#!/usr/bin/env python3
"""Collect public-sector job calls from official Peruvian government portals.

Gob.pe is used as a broad discovery source. A few official institutional
portals are also queried because Gob.pe's search markup can change and may
return no extractable links even when calls are published.
"""
import html
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

OUT = Path("convocatorias.json")
GOB_SEARCH = "https://www.gob.pe/busquedas"
SOURCES = [
    ("Programa Contigo", "https://contigo.gob.pe/TALENTO-HUMANO/"),
    ("Autoridad Portuaria Nacional", "https://reclutamiento.apn.gob.pe/convocatorias-cas/?modalidad=cas"),
    ("SUNAT", "https://www.sunat.gob.pe/oportunidadlaboral/"),
]
QUERIES = [
    "convocatoria de trabajo",
    "convocatoria CAS vigente",
    "prácticas profesionales convocatoria",
]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; EmpleosPeruTech/1.1; +https://empleosperu.tech)",
    "Accept-Language": "es-PE,es;q=0.9,en;q=0.7",
}
TERMS = (
    "convocatoria", "proceso de selección", "proceso de seleccion",
    "prácticas", "practicas", "concurso público", "concurso publico",
    "oferta laboral", "vigente", "cas ", "cas-", "p.s.",
)
CLOSED = ("culminado", "concluido", "terminado", "cancelado", "desierto", "finalizado", "no vigente")


def clean(value):
    return " ".join(html.unescape(str(value or "")).split())


def normalize_url(href, base):
    url = urljoin(base, href or "").split("#")[0]
    return url.rstrip("/")


def add_result(results, title, url, source, institution, context="", location="Perú", published=""):
    title = clean(title)
    context = clean(context)
    if len(title) < 12 or not url:
        return
    lowered = (title + " " + context).lower()
    # Reject results explicitly marked closed. For sources with a separate
    # state column, callers only pass rows marked vigente.
    if any(term in lowered for term in CLOSED):
        return
    if not any(term in lowered for term in TERMS) and not re.search(r"\b(?:CAS|P\.S\.?|PRAC)-?\d", title, re.I):
        return
    url = normalize_url(url, url)
    results.setdefault(url, {
        "title": title,
        "institution": institution or "Entidad pública",
        "location": clean(location) or "Perú",
        "published": clean(published),
        "url": url,
        "source": source,
        "status": "Verificar vigencia en la fuente oficial",
    })


def scrape_gobpe(session, results, errors):
    for query in QUERIES:
        try:
            response = session.get(
                GOB_SEARCH,
                params={"term": query, "contenido[]": "publicaciones", "sort_by": "recent"},
                timeout=25,
            )
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            for a in soup.select("a[href]"):
                href = normalize_url(a.get("href"), GOB_SEARCH)
                title = clean(a.get_text(" ", strip=True))
                if not title or len(title) < 12:
                    continue
                if urlparse(href).netloc not in ("gob.pe", "www.gob.pe"):
                    continue
                if "/tipos/" in href or href.rstrip("/") == GOB_SEARCH:
                    continue
                card = a
                for _ in range(4):
                    if card.parent:
                        card = card.parent
                context = clean(card.get_text(" ", strip=True))
                combined = (title + " " + context).lower()
                if not any(term in combined for term in TERMS):
                    continue
                date_match = re.search(r"(\d{1,2} de [a-záéíóú]+ de \d{4})", context, re.I)
                add_result(
                    results, title, href, "Gob.pe", "Entidad pública",
                    context=context, published=date_match.group(1) if date_match else "",
                )
        except Exception as exc:
            errors.append(f"Gob.pe ({query}): {exc}")


def scrape_contigo(session, results, errors):
    base = "https://contigo.gob.pe/TALENTO-HUMANO/"
    try:
        response = session.get(base, timeout=25)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for a in soup.select('a[href*="/jobs/"]'):
            title = clean(a.get_text(" ", strip=True))
            if not title:
                continue
            card = a
            for _ in range(4):
                if card.parent:
                    card = card.parent
            context = clean(card.get_text(" ", strip=True))
            # This portal labels each record's state explicitly. Only include
            # calls that the source currently marks as Vigente.
            if not re.search(r"\bvigente\b", context, re.I):
                continue
            if re.search(r"\b(concluido|cancelado|desierto|finalizado)\b", context, re.I):
                continue
            location_match = re.search(r"\b(Lima|Callao|Amazonas|Áncash|Ancash|Apurímac|Arequipa|Ayacucho|Cajamarca|Cusco|Huancavelica|Huánuco|Ica|Junín|La Libertad|Lambayeque|Loreto|Madre de Dios|Moquegua|Pasco|Piura|Puno|San Martín|Tacna|Tumbes|Ucayali)\b", context, re.I)
            location = location_match.group(1) if location_match else "Perú"
            add_result(results, title, normalize_url(a.get("href"), base), "Programa Contigo", "Programa Contigo", context, location)
    except Exception as exc:
        errors.append(f"Programa Contigo: {exc}")


def scrape_apn(session, results, errors):
    base = "https://reclutamiento.apn.gob.pe/convocatorias-cas/?modalidad=cas"
    try:
        response = session.get(base, timeout=25)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for row in soup.select("tr"):
            context = clean(row.get_text(" ", strip=True))
            if not re.search(r"\bvigente\b", context, re.I):
                continue
            if re.search(r"\b(finalizado|cancelado|desierto|concluido)\b", context, re.I):
                continue
            cells = row.find_all(["td", "th"], recursive=False)
            if len(cells) < 3:
                continue
            title = clean(cells[1].get_text(" ", strip=True))
            process = clean(cells[0].get_text(" ", strip=True))
            if not title or len(title) < 8:
                continue
            links = [a for a in row.select("a[href]") if not (a.get("href", "").strip().startswith("#"))]
            url = normalize_url(links[-1].get("href"), base) if links else base
            add_result(results, f"{process} — {title}", url, "Autoridad Portuaria Nacional", "Autoridad Portuaria Nacional", context)
    except Exception as exc:
        errors.append(f"Autoridad Portuaria Nacional: {exc}")


def scrape_sunat(session, results, errors):
    base = "https://www.sunat.gob.pe/oportunidadlaboral/"
    try:
        response = session.get(base, timeout=25)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        # SUNAT lists its current opportunities in a "Nuevas Convocatorias"
        # block. Capture the linked title and surrounding card, not just the
        # anchor text (which varies between desktop/mobile markup).
        for a in soup.select("a[href]"):
            title = clean(a.get_text(" ", strip=True))
            card = a
            for _ in range(3):
                if card.parent:
                    card = card.parent
            context = clean(card.get_text(" ", strip=True))
            combined = title + " " + context
            if not re.search(r"\bCAS\s*(?:N[º°.]?\s*)?\d+\s*[-–]\s*2026\b", combined, re.I):
                continue
            if re.search(r"\b(cerrada|finalizada|culminada|cancelada|desierta)\b", combined, re.I):
                continue
            url = normalize_url(a.get("href"), base)
            if urlparse(url).netloc not in ("sunat.gob.pe", "www.sunat.gob.pe", "unete.sunat.gob.pe"):
                continue
            if len(title) < 12:
                title_match = re.search(r"(CAS\s*(?:N[º°.]?\s*)?\d+\s*[-–]\s*2026\s*\|?\s*[^|]+)", combined, re.I)
                title = clean(title_match.group(1)) if title_match else title
            add_result(results, title, url, "SUNAT", "SUNAT", context=context)
    except Exception as exc:
        errors.append(f"SUNAT: {exc}")


def scrape_defensoria(session, results, errors):
    base = "https://www.defensoria.gob.pe/convocatorias/convocatorias-ant.php"
    try:
        response = session.get(base, timeout=25)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for a in soup.select("a[href]"):
            title = clean(a.get_text(" ", strip=True))
            if not title or len(title) < 12:
                continue
            card = a
            for _ in range(3):
                if card.parent:
                    card = card.parent
            context = clean(card.get_text(" ", strip=True))
            combined = title + " " + context
            # Only include links that clearly refer to a 2026 hiring process.
            if not re.search(r"(?:CAS|convocatoria|proceso de selección|proceso de seleccion|prácticas|practicas)", combined, re.I):
                continue
            if not re.search(r"2026", combined, re.I):
                continue
            if re.search(r"\b(cerrado|culminado|concluido|cancelado|desierto|finalizado)\b", combined, re.I):
                continue
            url = normalize_url(a.get("href"), base)
            if urlparse(url).netloc not in ("defensoria.gob.pe", "www.defensoria.gob.pe"):
                continue
            add_result(results, title, url, "Defensoría del Pueblo", "Defensoría del Pueblo", context=combined)
    except Exception as exc:
        errors.append(f"Defensoría del Pueblo: {exc}")



def scrape_mpfn(session, results, errors):
    """Extract hiring calls from the Public Ministry's official table."""
    base = "https://portal.mpfn.gob.pe/convoca/convocatorias/"
    try:
        response = session.get(base, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        today = date.today()
        for row in soup.select("tr"):
            cells = row.find_all(["td", "th"], recursive=False)
            if len(cells) < 8:
                continue
            context = clean(row.get_text(" ", strip=True))
            if not re.search(r"\\bvigente\\b", context, re.I):
                continue
            title = clean(cells[3].get_text(" ", strip=True))
            detail = clean(cells[4].get_text(" ", strip=True))
            published = clean(cells[5].get_text(" ", strip=True))
            end_text = clean(cells[7].get_text(" ", strip=True))
            end_match = re.search(r"(\\d{1,2}/\\d{1,2}/\\d{4})", end_text)
            if end_match:
                try:
                    if datetime.strptime(end_match.group(1), "%d/%m/%Y").date() < today:
                        continue
                except ValueError:
                    pass
            links = row.select("a[href]")
            url = normalize_url(links[0].get("href"), base) if links else base
            add_result(results, f"{title} — {detail}", url, "Ministerio Público", "Ministerio Público", context, location=clean(cells[1].get_text(" ", strip=True)) or "Perú", published=published)
    except Exception as exc:
        errors.append(f"Ministerio Público: {exc}")


def scrape_inpe(session, results, errors):
    """Extract recent CAS listings from INPE's official convocatorias page."""
    base = "https://www.inpe.gob.pe/convocatorias"
    try:
        response = session.get(base, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for a in soup.select("a[href]"):
            title = clean(a.get_text(" ", strip=True))
            card = a
            for _ in range(4):
                if card.parent:
                    card = card.parent
            context = clean(card.get_text(" ", strip=True))
            combined = title + " " + context
            if not re.search(r"convocatoria.*(?:CAS|2026)|(?:CAS|2026).*convocatoria", combined, re.I):
                continue
            if not re.search(r"2026", combined, re.I):
                continue
            if re.search(r"\\b(cerrado|culminado|concluido|cancelado|desierto|finalizado)\\b", combined, re.I):
                continue
            if title.lower() in ("bases", "anexos", "requisitos y cronograma", "descargar"):
                title_match = re.search(r"(?:CUARTA CONVOCATORIA )?CONVOCATORIA CAS[^.]{0,100}", combined, re.I)
                if title_match:
                    title = clean(title_match.group(0))
            url = normalize_url(a.get("href"), base)
            if urlparse(url).netloc not in ("inpe.gob.pe", "www.inpe.gob.pe"):
                continue
            pub_match = re.search(r"Publicado el (\\d{1,2} [A-Za-záéíóú]+ 2026)", combined, re.I)
            add_result(results, title, url, "INPE", "Instituto Nacional Penitenciario", context=combined, published=pub_match.group(1) if pub_match else "")
    except Exception as exc:
        errors.append(f"INPE: {exc}")


def main():
    session = requests.Session()
    session.headers.update(HEADERS)
    results = {}
    errors = []

    scrape_gobpe(session, results, errors)
    scrape_contigo(session, results, errors)
    scrape_apn(session, results, errors)
    scrape_sunat(session, results, errors)
    scrape_defensoria(session, results, errors)
    scrape_mpfn(session, results, errors)
    scrape_inpe(session, results, errors)

    items = sorted(results.values(), key=lambda item: item.get("published", ""), reverse=True)[:60]
    if not items:
        print("No se pudieron extraer convocatorias de las fuentes consultadas.")
        if errors:
            print("Avisos: " + " | ".join(errors))
        # Preserve existing data rather than replacing it with a misleading empty list.
        if OUT.exists():
            print("Se conserva convocatorias.json existente.")
            return
    payload = {
        "updated": datetime.now(timezone.utc).astimezone().date().isoformat(),
        "source": "Gob.pe y portales institucionales oficiales (Contigo, APN, SUNAT, Defensoría, Ministerio Público e INPE)",
        "count": len(items),
        "convocatorias": items,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Guardadas {len(items)} convocatorias/publicaciones oficiales.")
    if errors:
        print("Avisos de consulta: " + " | ".join(errors))


if __name__ == "__main__":
    main()
