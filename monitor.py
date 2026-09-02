import json
import os
import re
import unicodedata
from pathlib import Path
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.elcorteingles.es"

STATE_FILE = Path("state.json")

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]


PRODUCTS = [
    {
        "name": "The Fast and the Furious 25º Aniversario",
        "searches": [
            "the fast and the furious 25 aniversario",
            "a todo gas 25 aniversario",
            "fast furious 25 aniversario",
        ],
    },
    {
        "name": "Entrevista con el Vampiro",
        "searches": [
            "entrevista con el vampiro",
            "interview with the vampire",
        ],
    },
    {
        "name": "Outlander Serie Completa",
        "searches": [
            "outlander serie completa",
            "outlander blu ray",
        ],
    },
    {
        "name": "Midsommar",
        "searches": [
            "midsommar",
        ],
    },
    {
        "name": "United 93",
        "searches": [
            "united 93",
        ],
    },
    {
        "name": "28 Días Después",
        "searches": [
            "28 dias despues",
            "28 days later",
        ],
    },
    {
        "name": "Supergirl",
        "searches": [
            "supergirl",
        ],
    },
    {
        "name": "El Día de la Revelación",
        "searches": [
            "el dia de la revelacion",
            "the disclosure day",
        ],
    },
]


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}


def normalize(text):
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def load_state():
    if not STATE_FILE.exists():
        return {}

    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state):
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def search_ecI(query):
    """
    Busca en el buscador de El Corte Inglés.
    """
    url = f"{BASE_URL}/search/?s={quote_plus(query)}"

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30,
    )

    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    results = []

    for link in soup.find_all("a", href=True):
        href = link.get("href", "")
        title = link.get_text(" ", strip=True)

        if not title:
            continue

        if "/cine/" not in href:
            continue

        if href.startswith("/"):
            href = urljoin(BASE_URL, href)

        results.append(
            {
                "title": title,
                "url": href,
            }
        )

    return results


def looks_like_target(title, target):
    """
    Coincidencia flexible por palabras.
    No exige que aparezca 'steelbook' o 'edición metálica'.
    """
    t = normalize(title)
    target = normalize(target)

    words = [w for w in target.split() if len(w) > 2]

    matches = sum(word in t for word in words)

    # La mayoría de las palabras importantes deben aparecer.
    return matches >= max(1, int(len(words) * 0.65))


def extract_product(url):
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30,
    )

    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    text = soup.get_text(" ", strip=True)

    title = None
    price = None

    # Título
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(" ", strip=True)

    # Precio
    price_match = re.search(
        r"(\d{1,3}(?:[.,]\d{2})?)\s*€",
        text,
    )

    if price_match:
        price = price_match.group(1) + " €"

    # Indicadores básicos de disponibilidad
    unavailable_words = [
        "agotado",
        "no disponible",
        "temporalmente no disponible",
    ]

    available_words = [
        "añadir",
        "añadir a la cesta",
        "comprar",
        "reservar",
    ]

    normalized_text = normalize(text)

    if any(word in normalized_text for word in unavailable_words):
        availability = "No disponible"
    elif any(word in normalized_text for word in available_words):
        availability = "Disponible"
    else:
        availability = "Desconocido"

    return {
        "title": title or url,
        "price": price,
        "availability": availability,
        "url": url,
    }


def send_telegram(message):
    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_TOKEN}/sendMessage"
    )

    response = requests.post(
        url,
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "disable_web_page_preview": False,
        },
        timeout=30,
    )

    response.raise_for_status()


def main():
    state = load_state()
    new_state = dict(state)

    for product in PRODUCTS:

        candidates = []

        for query in product["searches"]:
            try:
                candidates.extend(search_ecI(query))
            except Exception as exc:
                print(f"Error buscando {query}: {exc}")

        # Eliminar duplicados
        unique = {}

        for item in candidates:
            unique[item["url"]] = item

        candidates = list(unique.values())

        for candidate in candidates:

            if not looks_like_target(
                candidate["title"],
                product["name"],
            ):
                continue

            try:
                info = extract_product(candidate["url"])
            except Exception as exc:
                print(
                    f"Error leyendo {candidate['url']}: {exc}"
                )
                continue

            key = info["url"]

            previous = state.get(key)

            current = {
                "target": product["name"],
                "title": info["title"],
                "price": info["price"],
                "availability": info["availability"],
                "url": info["url"],
            }

            new_state[key] = current

            # Primera vez que vemos el producto.
            if previous is None:
                message = (
                    "🚨 NUEVO PRODUCTO DETECTADO\n\n"
                    f"🎬 {info['title']}\n"
                    f"💿 {info['availability']}\n"
                    f"💰 {info['price'] or 'Precio no detectado'}\n\n"
                    f"🛒 {info['url']}"
                )

                send_telegram(message)
                continue

            # Cambió el precio.
            if previous.get("price") != info["price"]:
                message = (
                    "💰 CAMBIO DE PRECIO\n\n"
                    f"🎬 {info['title']}\n\n"
                    f"Antes: {previous.get('price') or '?'}\n"
                    f"Ahora: {info['price'] or '?'}\n\n"
                    f"🛒 {info['url']}"
                )

                send_telegram(message)

            # Cambió disponibilidad.
            if (
                previous.get("availability")
                != info["availability"]
            ):
                message = (
                    "🔔 CAMBIO DE DISPONIBILIDAD\n\n"
                    f"🎬 {info['title']}\n\n"
                    f"Antes: {previous.get('availability')}\n"
                    f"Ahora: {info['availability']}\n\n"
                    f"🛒 {info['url']}"
                )

                send_telegram(message)

    save_state(new_state)


if __name__ == "__main__":
    main()