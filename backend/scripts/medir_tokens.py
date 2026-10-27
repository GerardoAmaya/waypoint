"""Cuantos tokens cuesta entender una peticion, y revisarla.

**El de rutas estaba medido y el del modelo no.** La tabla de metricas del
README decia "una peticion a OpenRouteService en zona fria, cero con la cache
caliente" y del modelo, nada. Este guion llena ese hueco.

Mide el camino de produccion y no una reconstruccion: envuelve el cliente real
y deja que `interpret` e `interpret_revision` lo usen como siempre, de modo que
el prompt medido es el que corre. Si el prompt crece, este numero crece con el.

    docker compose exec api python -m scripts.medir_tokens

Gasta llamadas de verdad al modelo: una por frase, mas una revision.
"""

from __future__ import annotations

import statistics
import sys
from dataclasses import dataclass, field

from app.core.config import settings
from app.core.db import SessionLocal
from app.services.interpret import _default_client, interpret, interpret_revision

# Precio del modelo planificador, por millon de tokens. De la tabla de precios
# de Anthropic para claude-haiku-4-5. Si se cambia planner_model hay que
# cambiarlo aqui: el guion no lo sabe averiguar.
USD_ENTRADA_POR_MILLON = 1.00
USD_SALIDA_POR_MILLON = 5.00

# **El prompt del sistema no se puede cachear en este modelo.** Haiku 4.5 exige
# un prefijo de 4.096 tokens para que el cacheo se active, y el nuestro ronda
# los 3.000: con `cache_control` puesto no daria error, simplemente devolveria
# cache_creation_input_tokens: 0. Es la optimizacion obvia —el prompt es
# identico en todas las peticiones y son el 93% del gasto— y no aplica.
MINIMO_PARA_CACHEAR = 4096

# Frases reales, de lo simple a lo cargado. Las tres primeras son las que la
# pantalla de entrada ofrece como ejemplo, asi que son las que mas se escriben.
FRASES = [
    "Tres días por la Ruta de las Flores, odio madrugar",
    "El sábado en Santa Ana, quiero subir al volcán",
    "Dos días saliendo desde Santa Tecla, en carro",
    "Un día en Suchitoto",
    "Una semana por todo el país",
    "Dos días en la costa, sin museos",
    "Un día en San Salvador caminando, quiero almorzar hamburguesas",
    "Dos días desde el Hotel Barceló a partir del sábado a las 10 a.m., el "
    "primero en carro y el segundo a pie, ceno los dos días y vuelvo antes de "
    "las 11 p.m.",
]

# Las paradas que se le dan al modelo al revisar un dia. Ocho es un dia cargado:
# el contexto de la revision crece con ellas.
PARADAS = [
    "Volcán de San Salvador",
    "Mirador The Giant",
    "Los Ranchos",
    "Palm Plaza",
    "Iglesia El Carmen",
    "Montemilia",
    "Museo Tecleño",
    "Andián",
]


@dataclass
class Cuenta:
    entrada: list[int] = field(default_factory=list)
    salida: list[int] = field(default_factory=list)

    def anotar(self, uso) -> None:
        self.entrada.append(uso.input_tokens)
        self.salida.append(uso.output_tokens)

    @property
    def totales(self) -> list[int]:
        return [e + s for e, s in zip(self.entrada, self.salida, strict=True)]


class ClienteEspia:
    """El cliente real, anotando lo que cada respuesta dice que costo."""

    def __init__(self, real, cuenta: Cuenta) -> None:
        self._real = real
        self._cuenta = cuenta
        self.messages = _Mensajes(real.messages, cuenta)


class _Mensajes:
    def __init__(self, real, cuenta: Cuenta) -> None:
        self._real = real
        self._cuenta = cuenta

    def create(self, **kwargs):
        respuesta = self._real.create(**kwargs)
        self._cuenta.anotar(respuesta.usage)
        return respuesta


def _resumen(nombre: str, cuenta: Cuenta) -> None:
    if not cuenta.totales:
        print(f"{nombre}: sin medidas")
        return
    print(f"\n{nombre}  ({len(cuenta.totales)} llamadas)")
    print(f"  entrada : {statistics.mean(cuenta.entrada):7.0f} de media")
    print(f"  salida  : {statistics.mean(cuenta.salida):7.0f} de media")
    print(
        f"  total   : {statistics.mean(cuenta.totales):7.0f} de media   "
        f"mediana {statistics.median(cuenta.totales):.0f}   "
        f"peor {max(cuenta.totales)}"
    )
    usd = (
        statistics.mean(cuenta.entrada) * USD_ENTRADA_POR_MILLON
        + statistics.mean(cuenta.salida) * USD_SALIDA_POR_MILLON
    ) / 1_000_000
    print(f"  coste   : {usd:.5f} USD de media   {1 / usd:,.0f} por dolar")


def main() -> int:
    if not settings.anthropic_api_key:
        print("sin ANTHROPIC_API_KEY: este guion llama al modelo de verdad")
        return 1

    print(f"modelo: {settings.planner_model}")
    real = _default_client()

    armar = Cuenta()
    db = SessionLocal()
    try:
        for frase in FRASES:
            interpret(db, frase, client=ClienteEspia(real, armar))
            print(f"  {armar.totales[-1]:5} tokens  {frase[:58]}")
    finally:
        db.close()

    revisar = Cuenta()
    for cambio in ("menos carro", "sacá el museo y poné algo de comer"):
        interpret_revision(cambio, PARADAS, client=ClienteEspia(real, revisar))
        print(f"  {revisar.totales[-1]:5} tokens  (revisión) {cambio[:46]}")

    _resumen("Armar un itinerario", armar)
    _resumen("Revisar un día", revisar)

    print(
        "\nUn itinerario cuesta UNA llamada: el motor es determinista y no "
        "vuelve a consultar\nal modelo para armarlo. Cada revisión suma otra."
    )
    entrada = statistics.mean(armar.entrada)
    print(
        f"\nLa entrada es el {entrada / statistics.mean(armar.totales):.0%} del "
        f"gasto y casi no varía con la frase\n({min(armar.totales)}–"
        f"{max(armar.totales)} tokens): lo que se paga es el prompt, no la petición."
    )
    print(
        f"\nCachear ese prompt no es una opción en {settings.planner_model}: pide "
        f"{MINIMO_PARA_CACHEAR} tokens\nde prefijo y el nuestro son ~{entrada:.0f}. "
        "Por debajo del mínimo no cachea ni avisa."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
