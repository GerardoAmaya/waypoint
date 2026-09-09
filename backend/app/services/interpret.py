"""De una frase a restricciones verificables.

El modelo interpreta, el motor cumple. Esa division es la respuesta al riesgo
principal del proyecto: si el modelo armara el itinerario directamente,
"odio madrugar" seria una sugerencia que a veces ignora. Aqui se convierte en
una hora minima de inicio que el algoritmo no puede violar.

**El modelo no elige lugares.** Devuelve restricciones y el nombre de una
zona; el catalogo resuelve el resto. Por eso la metrica de lugares inventados
es cero por construccion y no por vigilancia.

**Lo que no se puede traducir se devuelve, no se descarta ni se disfraza.**
"quiero algo tranquilo" no tiene campo en el schema. Un modelo dejado a su
suerte hace una de dos cosas: lo tira en silencio, o lo mete a la fuerza en
preferred_categories inventando una equivalencia. La segunda es peor porque
parece que funciono. Va a `unmapped` y el usuario lo ve.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import time

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Category
from app.schemas import ItineraryRequest
from app.services.geocode import ResolvedArea, resolve_area, zone_names

logger = logging.getLogger(__name__)

MAX_PHRASE_LENGTH = 600

SYSTEM_PROMPT = """\
Sos el traductor de un planificador de viajes por El Salvador. Convertis lo \
que pide una persona en lenguaje natural a restricciones verificables.

Respondes UNICAMENTE con un objeto JSON, sin texto antes ni despues y sin \
marcas de bloque de codigo.

Campos:
- "area": string. La zona o lugar donde quiere viajar, tal como lo nombro. \
Si no menciona ninguno, null.
- "days": entero de 1 a 7. Si no lo dice, 1.
- "earliest_start": "HH:MM". Hora minima de inicio del dia. "odio madrugar" o \
"salir tarde" son cerca de las 10:00 u 11:00. Por defecto "09:00".
- "latest_end": "HH:MM". Hora maxima de fin. Por defecto "20:00".
- "max_travel_km_per_day": numero. Kilometros maximos de traslado por dia. \
"no quiero pasarme el dia en el carro" es cerca de 30. "caminando" o "sin \
carro" es cerca de 8. Por defecto 25.
- "mode": "driving" o "walking". Por defecto "driving".
- "preferred_categories": lista de estas y solo estas: "food", "nature", \
"culture", "viewpoint", "attraction", "lodging".
- "avoided_categories": la misma lista.
- "include_meals": booleano. Por defecto true.
- "max_stops_per_day": entero de 1 a 12. Por defecto 5.
- "unmapped": lista de strings.

Sobre "unmapped", que es el campo que mas importa: pone ahi, con las palabras \
de la persona, todo lo que entendiste pero NO pudiste representar en los \
campos de arriba. Preferencias de ambiente ("tranquilo", "romantico"), de \
presupuesto, de compania, de clima, nombres de lugares puntuales que quiere \
visitar, o cualquier cosa que el schema no cubra.

NUNCA fuerces algo dentro de una categoria porque se parece. "tranquilo" no \
es "nature". Si dudas entre un campo y "unmapped", elegi "unmapped": que la \
persona vea que no lo tomaste en cuenta es mejor que que crea que si.

No inventes nombres de lugares ni los pongas en "area" si la persona no los \
menciono."""


@dataclass
class Interpretation:
    """El resultado de traducir una frase.

    `notes` lleva los ajustes que hubo que aplicar y `unmapped` lo que no se
    pudo traducir. Las dos cosas viajan al usuario: un planificador que
    silenciosamente recorta lo que pediste es peor que uno que lo dice.
    """

    request: ItineraryRequest | None = None
    area: ResolvedArea | None = None
    area_text: str | None = None
    unmapped: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.request is not None


class InterpretError(Exception):
    """No se pudo traducir la frase."""


def _clean_json(texto: str) -> str:
    """Quita las marcas de bloque que el modelo agrega aunque se le pida que no."""
    limpio = texto.strip()
    if limpio.startswith("```"):
        limpio = limpio.split("\n", 1)[-1]
        limpio = limpio.rsplit("```", 1)[0]
    return limpio.strip()


def _parse_time(valor, por_defecto: time, notes: list[str], campo: str) -> time:
    if not isinstance(valor, str):
        return por_defecto
    try:
        horas, minutos = valor.split(":")[:2]
        return time(int(horas) % 24, int(minutos) % 60)
    except (ValueError, TypeError):
        notes.append(f"no se entendio la hora {valor!r} para {campo}")
        return por_defecto


def _clamp(valor, minimo, maximo, por_defecto, notes: list[str], campo: str):
    """Recorta al rango permitido y deja constancia de que se recorto.

    Recortar en silencio es la forma mas facil de que alguien pida diez dias,
    reciba siete, y no entienda por que.
    """
    if valor is None:
        return por_defecto
    try:
        numero = type(por_defecto)(valor)
    except (TypeError, ValueError):
        notes.append(f"no se entendio {valor!r} para {campo}")
        return por_defecto

    if numero < minimo:
        notes.append(f"se pidio {campo}={numero} y el minimo es {minimo}")
        return minimo
    if numero > maximo:
        notes.append(f"se pidio {campo}={numero} y el maximo es {maximo}")
        return maximo
    return numero


def _categories(valores, notes: list[str], campo: str) -> list[Category]:
    validas: list[Category] = []
    if not isinstance(valores, list):
        return validas

    for valor in valores:
        try:
            categoria = Category(valor)
        except (ValueError, TypeError):
            notes.append(f"{valor!r} no es una categoria conocida, se ignoro")
            continue
        if categoria not in validas:
            validas.append(categoria)
    return validas


def _strings(valores) -> list[str]:
    if not isinstance(valores, list):
        return []
    return [str(v).strip() for v in valores if str(v).strip()]


def _call_model(frase: str, client=None) -> dict:
    """Le pide al modelo el JSON y lo devuelve parseado."""
    if client is None:
        client = _default_client()

    respuesta = client.messages.create(
        model=settings.planner_model,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": frase}],
    )

    texto = "".join(
        bloque.text for bloque in respuesta.content if getattr(bloque, "type", "") == "text"
    )
    try:
        datos = json.loads(_clean_json(texto))
    except json.JSONDecodeError as exc:
        raise InterpretError("el modelo no devolvio JSON valido") from exc

    if not isinstance(datos, dict):
        raise InterpretError("el modelo devolvio algo que no es un objeto")
    return datos


def _default_client():
    if not settings.anthropic_api_key:
        raise InterpretError("no hay ANTHROPIC_API_KEY configurada")

    from anthropic import Anthropic

    return Anthropic(api_key=settings.anthropic_api_key)


def interpret(db: Session, frase: str, client=None) -> Interpretation:
    """Traduce la frase a restricciones y resuelve la zona contra el catalogo."""
    frase = (frase or "").strip()
    if not frase:
        return Interpretation(error="hace falta que escribas que queres hacer")
    if len(frase) > MAX_PHRASE_LENGTH:
        return Interpretation(
            error=f"la peticion es muy larga, el maximo son {MAX_PHRASE_LENGTH} caracteres"
        )

    try:
        datos = _call_model(frase, client)
    except InterpretError as exc:
        logger.warning("no se pudo interpretar la frase: %s", exc)
        return Interpretation(error=str(exc))

    notes: list[str] = []
    unmapped = _strings(datos.get("unmapped"))

    texto_area = datos.get("area")
    texto_area = texto_area.strip() if isinstance(texto_area, str) else None

    if not texto_area:
        return Interpretation(
            area_text=None,
            unmapped=unmapped,
            notes=notes,
            error=(
                "no dijiste a donde queres ir. Probá con una zona como "
                + ", ".join(zone_names()[:4])
                + " u otra."
            ),
        )

    area = resolve_area(db, texto_area)
    if area is None:
        return Interpretation(
            area_text=texto_area,
            unmapped=unmapped,
            notes=notes,
            error=(
                f"no encontré {texto_area!r} en el catálogo. Las zonas que conozco "
                "son: " + ", ".join(zone_names())
            ),
        )

    if area.source == "catalog":
        notes.append(
            f"{texto_area!r} no es una zona conocida; se centró la búsqueda en "
            f"{area.name}, que sí está en el catálogo"
        )

    preferidas = _categories(datos.get("preferred_categories"), notes, "preferred")
    evitadas = _categories(datos.get("avoided_categories"), notes, "avoided")

    # Una categoria en las dos listas es contradictoria y el schema la rechaza.
    # Gana evitarla: es mas facil que alguien pida "sin museos" y el modelo
    # tambien la marque como preferida por el contexto, que al reves.
    solapadas = [c for c in preferidas if c in evitadas]
    for categoria in solapadas:
        preferidas.remove(categoria)
        notes.append(
            f"{categoria.value} quedó como preferida y evitada a la vez; se respetó evitarla"
        )

    inicio = _parse_time(datos.get("earliest_start"), time(9, 0), notes, "earliest_start")
    fin = _parse_time(datos.get("latest_end"), time(20, 0), notes, "latest_end")

    # El schema rechaza el horario invertido al construir, asi que hay que
    # arreglarlo antes y no despues.
    if inicio >= fin:
        notes.append(
            "la hora de inicio no puede ser posterior a la de fin; se usaron las "
            "horas por defecto"
        )
        inicio, fin = time(9, 0), time(20, 0)

    try:
        peticion = ItineraryRequest(
            days=_clamp(datos.get("days"), 1, 7, 1, notes, "days"),
            center_lat=area.lat,
            center_lon=area.lon,
            radius_m=area.radius_m,
            earliest_start=inicio,
            latest_end=fin,
            max_travel_km_per_day=_clamp(
                datos.get("max_travel_km_per_day"), 1.0, 500.0, 25.0, notes, "max_travel_km"
            ),
            mode=datos.get("mode")
            if datos.get("mode") in ("driving", "walking")
            else "driving",
            preferred_categories=preferidas,
            avoided_categories=evitadas,
            include_meals=bool(datos.get("include_meals", True)),
            max_stops_per_day=_clamp(
                datos.get("max_stops_per_day"), 1, 12, 5, notes, "max_stops_per_day"
            ),
        )
    except ValidationError as exc:
        # Red de seguridad: los campos se recortan uno por uno mas arriba, pero
        # el schema tambien valida combinaciones, y un modelo puede producir una
        # que no se haya previsto. Mejor un mensaje que un 500.
        logger.warning("el modelo produjo una peticion invalida: %s", exc)
        return Interpretation(
            area=area,
            area_text=texto_area,
            unmapped=unmapped,
            notes=notes,
            error="no se pudo armar una peticion valida con lo que pediste",
        )

    return Interpretation(
        request=peticion,
        area=area,
        area_text=texto_area,
        unmapped=unmapped,
        notes=notes,
    )
