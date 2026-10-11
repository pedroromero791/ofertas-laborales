#!/usr/bin/env python3
"""Collect recent public-sector job calls from official Gob.pe search pages."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
import requests
from bs4 import BeautifulSoup

OUT = Path("convocatorias.json")
BASE = "https://www.gob.pe/busquedas"
QUERIES = [
    "convocatoria de trabajo",
    "convocatoria CAS vigente",
    "prácticas profesionales convocatoria",
]
HEADERS = {"User-Agent": "EmpleosPeruTech/1.0 (+https://empleosperu.tech)"}
TERMS = ("convocatoria", "proceso de selección", "proceso de seleccion", "prácticas", "practicas", "concurso público", "concurso publico")
CLOSED = ("culminado", "concluido", "terminado", "cancelado", "desierto", "finalizado")

def main():
    session = requests.Session()
    session.headers.update(HEADERS)
    results = {}
    errors = []
    for query in QUERIES:
        params = {"term": query, "contenido[]": "publicaciones", "sort_by": "recent"}
        try:
            response = session.get(BASE, params=params, timeout=25)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            for a in soup.select('a[href]'):
                href = a.get("href", "")
                title = " ".join(a.get_text(" ", strip=True).split())
                if not title or len(title) < 12:
                    continue
                if "/institucion/" not in href or not any(term in (href + " " + title).lower() for term in TERMS):
                    continue
                if any(term in title.lower() for term in CLOSED):
                    continue
                if href.startswith("/"):
                    href = "https://www.gob.pe" + href
                if not href.startswith("https://www.gob.pe/"):
                    continue
                # Skip generic category/compendium pages when an individual publication is available.
                if "/tipos/" in href:
                    continue
                card = a
                for _ in range(5):
                    if card.parent:
                        card = card.parent
                context = " ".join(card.get_text(" ", strip=True).split())
                date_match = re.search(r"(\d{1,2} de [a-záéíóú]+ de \d{4})", context, re.I)
                published = date_match.group(1) if date_match else ""
                institution = ""
                match = re.search(r"([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ0-9 .&()/-]{2,})", context)
                if match:
                    institution = match.group(1).strip(" .-")
                key = href.split("?")[0].rstrip("/")
                results.setdefault(key, {
                    "title": title,
                    "institution": institution or "Entidad pública",
                    "location": "Perú",
                    "published": published,
                    "url": key,
                    "source": "Gob.pe",
                    "status": "Verificar vigencia en la fuente oficial"
                })
        except Exception as exc:
            errors.append(f"{query}: {exc}")
    # Keep a successful empty result from overwriting a previously populated file.
    items = sorted(results.values(), key=lambda x: x.get("published", ""), reverse=True)[:60]
    if not items and OUT.exists():
        print("No se encontraron resultados; se conserva convocatorias.json existente.")
        if errors:
            print("\n".join(errors))
        return
    payload = {
        "updated": datetime.now(timezone.utc).astimezone().date().isoformat(),
        "source": "Gob.pe — publicaciones oficiales",
        "count": len(items),
        "convocatorias": items
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Guardadas {len(items)} publicaciones oficiales.")
    if errors:
        print("Avisos de consulta: " + " | ".join(errors))

if __name__ == "__main__":
    main()
