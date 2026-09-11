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
import uuid
from dataclasses import dataclass, field
from datetime import date, time, timedelta

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.reloj import en_palabras, hoy
from app.models import Category
from app.schemas import ItineraryRequest
from app.services.geocode import (
    ResolvedArea,
    buscar_lugar,
    resolve_area,
    resolve_must_visit,
    zone_names,
)
from app.services.places import PlaceHit

logger = logging.getLogger(__name__)

MAX_PHRASE_LENGTH = 600

# Hasta cuando se acepta una fecha de viaje.
#
# Un año es generoso para planificar y suficiente para atajar el error real: el
# modelo resuelve "el 20 de diciembre" contra el año en curso, y si se equivoca
# de año la fecha sale disparada en vez de quedar cerca. Mas alla de esto se
# avisa y se planifica para hoy, que es lo unico que no puede estar mal.
HORIZONTE_DIAS = 365

# Radio de busqueda cuando lo unico que se dijo es de donde se sale.
#
# Doce kilometros es lo que se recorre en un dia saliendo de un punto y
# volviendo: mas que un barrio y menos que un municipio entero. Quien quiera
# otra cosa nombra la zona y manda el radio de la zona.
RADIO_DESDE_LA_PARTIDA_M = 12_000

SYSTEM_PROMPT = """\
Sos el traductor de un planificador de viajes por El Salvador. Convertis lo \
que pide una persona en lenguaje natural a restricciones verificables.

Respondes UNICAMENTE con un objeto JSON, sin texto antes ni despues y sin \
marcas de bloque de codigo.

Campos:
- "area": string. La zona o lugar donde quiere viajar, tal como lo nombro. \
Si no menciona ninguno, null.
- "days": entero de 1 a 7. Si no lo dice, 1.
- "start_date": "YYYY-MM-DD" o null. El dia en que arranca el viaje, SOLO si \
lo dice. "hoy", "manana", "el sabado", "el 20 de diciembre", "el otro fin de \
semana" son fechas: resolvelas contra el dia de hoy, que va al final de estas \
instrucciones. Un dia de la semana a secas es el proximo que viene, no el que \
ya paso. Si no habla de cuando viaja, null: mas vale no saber la fecha que \
inventar una.
- "earliest_start": "HH:MM". Hora minima de inicio del dia. "odio madrugar" o \
"salir tarde" son cerca de las 10:00 u 11:00. Por defecto "09:00".
- "latest_end": "HH:MM". Hora maxima de fin. Por defecto "20:00".
- "max_travel_km_per_day": numero o null. Kilometros maximos de traslado por \
dia. Ponelo SOLO si habla de cuanto se quiere mover: "no quiero pasarme el dia \
en el carro" es cerca de 30, "poco carro" cerca de 15, un numero dicho se \
respeta. Si no habla de eso, null: el largo del dia lo deciden el horario y \
las ganas, y un techo inventado le recorta el viaje que si pidio.
- "mode": "driving" o "walking". Por defecto "driving". Es el modo de todo el \
viaje.
- "day_modes": objeto de numero de dia a modo, SOLO cuando distintos dias van \
distinto. "el primer dia en coche y el segundo a pie" es \
{"1": "driving", "2": "walking"}. Si todo el viaje va igual, dejalo vacio y \
usa "mode".
- "preferred_categories": lista de estas y solo estas: "food", "nature", \
"culture", "viewpoint", "attraction", "lodging".
- "avoided_categories": la misma lista.
- "must_include_categories": la misma lista. Van aca las categorias que la \
persona EXIGE, no las que le gustan. "quiero ver minimo un museo" y "que \
incluya al menos un mirador" son requisitos: culture y viewpoint. "me gustan \
los museos" o "prefiero naturaleza" son preferencias y van en \
preferred_categories. La diferencia es que un requisito se cumple o se \
incumple, y una preferencia solo sube las probabilidades.
- "include_meals": booleano. Por defecto true.
- "must_include_meals": lista con "lunch" y/o "dinner". Van SOLO las comidas \
que nombra: "voy a cenar los dos dias" es ["dinner"], "almuerzo y cena" es \
["lunch", "dinner"]. Si solo dice que come, o no habla de comidas, dejala \
vacia: la diferencia es que una comida nombrada que el itinerario no pueda \
darle se le explica, y una que no nombro, no.
- "meal_minutes": entero de 20 a 240. Cuanto dura cada comida, en minutos. \
Por defecto 90. "almuerzo tranquilo de dos horas" es 120; "comemos algo \
rapido" o "no quiero perder tiempo comiendo" es cerca de 40. Solo si lo dice.
- "category_minutes": objeto de categoria a minutos, SOLO cuando dice cuanto \
tiempo quiere pasar en un tipo de lugar. "quiero pasar dos horas en el parque" \
es {"nature": 120}; "los museos rapido" es {"culture": 40}. Las claves son las \
mismas seis categorias. Si no dice ningun tiempo, dejalo vacio.
- "max_stops_per_day": entero de 1 a 12, o null. Son los lugares que quiere \
visitar; el sitio de donde sale no cuenta. **Ponlo SOLO si dice un numero o \
una cantidad**: "tres paradas", "pocos lugares" es 3, "un dia bien cargado" es \
8. Si no habla de cuantos lugares, null: el itinerario se llena hasta la hora \
que pidio, y un numero inventado se lo acortaria.
- "start_place": string. El lugar concreto de donde arranca el dia, tal como lo \
nombro: "Pizza Hut La Gran Via", "el Hotel Barcelo", "mi casa en Mejicanos". Es \
de donde SALE, no lo que quiere visitar. Si no dice de donde sale, null.
- "must_visit": lista de objetos {"name": string, "minutes": entero o null}. \
Los lugares CONCRETOS que dice que quiere visitar, con el nombre tal como lo \
dijo: "quiero ir al Jardin Botanico y pasar dos horas ahi" es [{"name": \
"Jardin Botanico", "minutes": 120}]. Van aca los que nombra; una zona ("por el \
occidente") va en "area", y el sitio de donde SALE va en "start_place". Si no \
nombra ningun lugar que quiera visitar, lista vacia. **Nombrar un lugar aqui NO \
reemplaza a "area"**: si la frase dice la zona, "area" va igual.
- "return_to_start": booleano. Si vuelve al punto de partida al terminar. \
"regreso en la noche", "y de vuelta al hotel", "vuelvo a dormir ahi" son true. \
Por defecto false.
- "unmapped": lista de strings.

Sobre "start_place" y "area", que se confunden facil: "area" es la zona donde \
va a pasear y "start_place" el sitio puntual de donde sale. "quiero pasear por \
Suchitoto saliendo del Hotel X" tiene los dos. Cuando alguien dice de donde \
sale y nada mas, poner ese lugar en "start_place" y dejar "area" en null: el \
punto de partida ya dice donde buscar.

Sobre "unmapped", que es el campo que mas importa: pone ahi, con las palabras \
de la persona, todo lo que entendiste pero NO pudiste representar en los \
campos de arriba. Preferencias de ambiente ("tranquilo", "romantico"), de \
presupuesto, de compania, de clima, nombres de lugares puntuales que quiere \
visitar, o cualquier cosa que el schema no cubra.

NUNCA fuerces algo dentro de una categoria porque se parece. "tranquilo" no \
es "nature". Si dudas entre un campo y "unmapped", elegi "unmapped": que la \
persona vea que no lo tomaste en cuenta es mejor que que crea que si.

**Lo que SI representaste no va en "unmapped".** Si tradujiste "odio \
madrugar" a earliest_start, ya lo tomaste en cuenta y no queda nada sin \
representar: repetirlo en "unmapped" le dice a la persona que lo ignoraste \
cuando en realidad lo aplicaste. Antes de poner algo en "unmapped", revisa si \
alguno de los campos de arriba lo cubre.

Una categoria exigida NO se repite en preferred_categories: exigirla ya es lo \
mas fuerte que se puede pedir.

Si dice la hora a la que sale, va en "earliest_start"; si dice hasta que hora \
puede, en "latest_end". "salgo a las 12 y termino como a las 10 de la noche" \
son earliest_start "12:00" y latest_end "22:00".

**Una frase puede estar cubierta a medias, y entonces se parte.** Pone en los \
campos la parte que si podes representar y en "unmapped" solo lo que sobra. \
"quiero comer bien" son dos cosas: que le importa la comida, que si es \
preferred_categories ["food"], y que la quiere buena, que NO se puede \
representar porque el catalogo no tiene valoraciones de nadie. Entonces va \
food en preferred_categories y "comer bien" en unmapped. Mandar la frase \
entera a "unmapped" le dice que ignoraste hasta la parte que si aplicaste.

Ejemplos de lo que va en "unmapped": "algo tranquilo", "romantico", \
"presupuesto bajo", "vamos con ninos", "que no llueva", "comida rica".
Ejemplos de lo que NO va: "odio madrugar" (es earliest_start), "sin museos" \
(es avoided_categories), "poco carro" (es max_travel_km_per_day), "tres dias" \
(es days).

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
    # El lugar del que sale el dia, ya resuelto contra el catalogo. No va
    # dentro de `request` porque ahi solo entran valores serializables y esto
    # es una parada del catalogo.
    start_place: PlaceHit | None = None
    return_to_start: bool = False
    # Lugares pedidos con nombre, ya resueltos contra el catalogo.
    must_include_places: list[PlaceHit] = field(default_factory=list)
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


def _parse_date(valor, referencia: date, notes: list[str]) -> date | None:
    """Valida la fecha que devolvio el modelo, o devuelve None con aviso.

    **Se comprueba aunque la haya resuelto el modelo.** Darle el dia de hoy
    hace que pueda resolver "el sabado"; no hace que la aritmetica le salga
    bien. Las dos formas en que se equivoca son medibles y las dos se atajan
    aqui: una fecha que ya paso y una que cae a años de distancia.

    None es "no hay fecha utilizable", y quien llama la reemplaza por hoy. Se
    avisa siempre: planificar para otro dia del que se pidio, en silencio, es
    la clase de fallo que se descubre estando en el lugar equivocado.
    """
    if not isinstance(valor, str) or not valor.strip():
        return None

    try:
        fecha = date.fromisoformat(valor.strip())
    except ValueError:
        notes.append(f"no entendí {valor!r} como una fecha; se planificó para hoy")
        return None

    if fecha < referencia:
        notes.append(
            f"{fecha.isoformat()} ya pasó; se planificó para hoy. Si querías otra "
            "fecha, escribila con el día y el mes"
        )
        return None

    if fecha > referencia + timedelta(days=HORIZONTE_DIAS):
        notes.append(f"{fecha.isoformat()} queda a más de un año; se planificó para hoy")
        return None

    return fecha


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


def _day_modes(valores, notes: list[str]) -> dict[str, str]:
    """Limpia el modo por dia que devolvio el modelo.

    Solo entran dias que son numeros y modos que el motor conoce. Un dia "3"
    en un viaje de dos no molesta —mode_for() nunca lo busca— asi que no vale
    la pena rechazar la peticion entera por eso.
    """
    if not isinstance(valores, dict):
        return {}

    salida: dict[str, str] = {}
    for numero, modo in valores.items():
        if modo not in ("driving", "walking"):
            notes.append(f"no reconocí el modo {modo!r}; ese día va como el resto")
            continue
        try:
            salida[str(int(numero))] = modo
        except (TypeError, ValueError):
            notes.append(f"no reconocí el día {numero!r} para el modo de viaje")
    return salida


def _category_minutes(valores, notes: list[str]) -> dict[Category, int]:
    """Limpia los minutos por categoria que devolvio el modelo.

    Una categoria que no existe se descarta con aviso y no tumba la peticion:
    el resto de lo que pidio la persona sigue siendo valido, y perder un viaje
    entero porque el modelo escribio "parque" en vez de "nature" seria una
    mala forma de fallar.
    """
    if not isinstance(valores, dict):
        return {}

    salida: dict[Category, int] = {}
    for nombre, minutos in valores.items():
        try:
            categoria = Category(str(nombre).strip().lower())
        except ValueError:
            notes.append(f"no reconocí la categoría {nombre!r} para el tiempo de visita")
            continue
        try:
            entero = int(minutos)
        except (TypeError, ValueError):
            notes.append(f"no entendí {minutos!r} como minutos de {categoria.value}")
            continue
        # Fuera de rango se descarta en vez de recortarse a un numero
        # inventado: sin entrada, la categoria usa la duracion por defecto del
        # motor, que es mejor respuesta que un valor que nadie pidio.
        if not 10 <= entero <= 480:
            notes.append(
                f"{entero} minutos en {categoria.value} está fuera de lo razonable; "
                "se usó la duración normal"
            )
            continue
        salida[categoria] = entero
    return salida


def _meals(valores, notes: list[str]) -> list[str]:
    """Limpia las comidas pedidas con nombre.

    Solo almuerzo y cena: son las dos franjas que el motor sabe colocar. Un
    "breakfast" se descarta con aviso en vez de aceptarse y no cumplirse
    nunca, que es la peor de las dos respuestas.
    """
    salida: list[str] = []
    for valor in _strings(valores):
        clave = valor.strip().lower()
        if clave in ("lunch", "dinner"):
            if clave not in salida:
                salida.append(clave)
        else:
            notes.append(f"no reconocí {valor!r} como una comida; solo almuerzo y cena")
    return salida


def _strings(valores) -> list[str]:
    if not isinstance(valores, list):
        return []
    return [str(v).strip() for v in valores if str(v).strip()]


def _fecha_de_hoy_para_el_modelo(fecha: date) -> str:
    """La linea que le dice al modelo en que dia vive.

    **Sin esto no puede resolver "el sabado".** Un modelo no sabe que dia es
    hoy: lo unico que tiene son las fechas de su entrenamiento, asi que sin
    decirselo resuelve los dias de la semana contra un año cualquiera y la
    fecha sale plausible y equivocada.
    """
    return (
        f"Hoy es {en_palabras(fecha)} de {fecha.year}, o sea {fecha.isoformat()}. "
        'Resolve contra esa fecha "hoy", "manana" y los dias de la semana.'
    )


def _call_model(frase: str, client=None, fecha: date | None = None) -> dict:
    """Le pide al modelo el JSON y lo devuelve parseado."""
    if client is None:
        client = _default_client()

    respuesta = client.messages.create(
        model=settings.planner_model,
        max_tokens=1024,
        system=(f"{SYSTEM_PROMPT}\n\n{_fecha_de_hoy_para_el_modelo(fecha or hoy())}"),
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


def _no_se_encontro(texto: str, sugerencias: list[PlaceHit]) -> str:
    """El mensaje de que no se encontro el lugar, con lo que si hay parecido.

    **"Probá con el nombre como aparece en el mapa" era un callejon sin
    salida.** El caso real: alguien escribio "Multiplaza San Salvador", el
    catalogo tiene "Centro Comercial Multiplaza" —activo, el mismo sitio— y la
    respuesta le pedia adivinar como estaba escrito. Desde fuera no hay forma.

    Sugerir no es sustituir: el dia sigue sin empezar en un lugar que nadie
    nombro. Lo que cambia es que ahora se dice cual podria ser, y la persona
    elige.
    """
    if not sugerencias:
        return (
            f"no encontré {texto!r} en el catálogo, y no quiero empezar el día "
            "en otro lugar parecido. Probá con el nombre como aparece en el "
            "mapa, o decime la zona y armo el día ahí."
        )

    nombres = [lugar.name for lugar in sugerencias]
    lista = nombres[0] if len(nombres) == 1 else ", ".join(nombres[:-1]) + " o " + nombres[-1]
    return (
        f"no encontré {texto!r} tal cual, y no quiero empezar el día en otro "
        f"lugar parecido sin preguntarte. ¿Era {lista}? Escribilo así y lo armo."
    )


def interpret(db: Session, frase: str, client=None) -> Interpretation:
    """Traduce la frase a restricciones y resuelve la zona contra el catalogo."""
    frase = (frase or "").strip()
    if not frase:
        return Interpretation(error="hace falta que escribas que queres hacer")
    if len(frase) > MAX_PHRASE_LENGTH:
        return Interpretation(
            error=f"la peticion es muy larga, el maximo son {MAX_PHRASE_LENGTH} caracteres"
        )

    # Una sola lectura del reloj para toda la interpretacion: si se leyera dos
    # veces, una peticion hecha a las 23:59:59 podria resolver "manana" contra
    # un dia y validarlo contra el siguiente.
    hoy_ = hoy()

    try:
        datos = _call_model(frase, client, hoy_)
    except InterpretError as exc:
        logger.warning("no se pudo interpretar la frase: %s", exc)
        return Interpretation(error=str(exc))

    notes: list[str] = []
    unmapped = _strings(datos.get("unmapped"))

    # Sin fecha se planifica para hoy, que es lo que quiere quien no la dice:
    # "un dia por Suchitoto" es un plan para ahora, no un plan sin cuando. La
    # fecha se devuelve al cliente y se muestra, asi que suponerla no es
    # suponerla en silencio.
    fecha_inicio = _parse_date(datos.get("start_date"), hoy_, notes) or hoy_

    pedidos: list[PlaceHit] = []
    minutos_por_lugar: dict[uuid.UUID, int] = {}
    for entrada in datos.get("must_visit") or []:
        if isinstance(entrada, str):
            entrada = {"name": entrada}
        if not isinstance(entrada, dict):
            continue
        nombre = str(entrada.get("name") or "").strip()
        if not nombre:
            continue
        hallado = resolve_must_visit(db, nombre)
        if hallado is None:
            # **No se sustituye por el parecido.** Prometer el lugar que
            # pidieron y llevar a otro es peor que admitir que no se encontro,
            # que es la misma regla del punto de partida. Aca no se corta la
            # peticion entera: el resto del viaje sigue siendo valido y esto
            # se cuenta como algo que no se supo usar.
            unmapped.append(nombre)
            continue
        if not any(p.id == hallado.id for p in pedidos):
            pedidos.append(hallado)
        crudos = entrada.get("minutes")
        if crudos is not None:
            try:
                minutos = int(crudos)
            except (TypeError, ValueError):
                notes.append(f"no entendí {crudos!r} como minutos en {nombre}")
            else:
                if 10 <= minutos <= 480:
                    minutos_por_lugar[hallado.id] = minutos
                else:
                    notes.append(
                        f"{minutos} minutos en {nombre} está fuera de lo razonable; "
                        "se usó la duración normal"
                    )

    texto_partida = datos.get("start_place")
    texto_partida = texto_partida.strip() if isinstance(texto_partida, str) else None
    partida: PlaceHit | None = None

    if texto_partida:
        buscado = buscar_lugar(db, texto_partida)
        partida = buscado.hit
        if partida is None:
            # **Se dice, no se sustituye.** El caso real: "Hotel Barcelo" no
            # esta en el catalogo, y con umbral bajo la busqueda difusa devuelve
            # "Hotel La Parcela", que es otro sitio a veinte kilometros. Un dia
            # que arranca donde el usuario no esta se descubre estando ahi.
            return Interpretation(
                area_text=None,
                unmapped=unmapped,
                notes=notes,
                error=_no_se_encontro(texto_partida, buscado.sugerencias),
            )

    texto_area = datos.get("area")
    texto_area = texto_area.strip() if isinstance(texto_area, str) else None

    area: ResolvedArea | None = None

    if not texto_area and partida is not None:
        # El punto de partida ya dice donde buscar: quien nombra de donde sale
        # y nada mas no tiene que nombrar tambien la zona.
        area = ResolvedArea(
            name=partida.name,
            lat=partida.lat,
            lon=partida.lon,
            radius_m=RADIO_DESDE_LA_PARTIDA_M,
            source="start",
        )
    elif not texto_area and pedidos:
        # Un lugar que se pidio visitar tambien dice donde buscar. Hace falta
        # porque el campo "must_visit" compite con "area" en el prompt y el
        # modelo se queda con uno: medido, "un dia en San Salvador, quiero
        # visitar Metrocentro y Metrosur" devolvia area null y los dos centros
        # comerciales en must_visit, y la peticion moria con "no dijiste a
        # donde queres ir" teniendo la zona escrita en la frase.
        area = ResolvedArea(
            name=pedidos[0].name,
            lat=pedidos[0].lat,
            lon=pedidos[0].lon,
            radius_m=RADIO_DESDE_LA_PARTIDA_M,
            source="start",
        )
    elif not texto_area:
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
    else:
        area = resolve_area(db, texto_area)
        if area is None:
            return Interpretation(
                area_text=texto_area,
                unmapped=unmapped,
                notes=notes,
                error=(
                    f"no encontré {texto_area!r} en el catálogo. Las zonas que "
                    "conozco son: " + ", ".join(zone_names())
                ),
            )

    if area.source == "catalog":
        notes.append(
            f"{texto_area!r} no es una zona conocida; se centró la búsqueda en "
            f"{area.name}, que sí está en el catálogo"
        )

    preferidas = _categories(datos.get("preferred_categories"), notes, "preferred")
    evitadas = _categories(datos.get("avoided_categories"), notes, "avoided")
    exigidas = _categories(datos.get("must_include_categories"), notes, "must_include")

    # Exigir y evitar la misma categoria no se puede cumplir. Gana evitarla por
    # la misma razon que con las preferidas: es mas facil que el modelo la
    # marque como exigida por el contexto que al reves.
    for categoria in [c for c in exigidas if c in evitadas]:
        exigidas.remove(categoria)
        notes.append(
            f"{categoria.value} quedó exigida y evitada a la vez; se respetó evitarla"
        )

    # Exigirla ya es lo mas fuerte que se puede pedir: repetirla como preferida
    # no agrega nada y deja el reporte diciendo dos cosas del mismo pedido.
    for categoria in [c for c in preferidas if c in exigidas]:
        preferidas.remove(categoria)

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
            start_date=fecha_inicio,
            center_lat=area.lat,
            center_lon=area.lon,
            radius_m=area.radius_m,
            earliest_start=inicio,
            latest_end=fin,
            # Sin numero pedido se deja en None y manda el reloj, igual que
            # max_stops_per_day. _clamp necesita un valor por defecto, asi que
            # la ausencia se resuelve antes de llamarlo.
            max_travel_km_per_day=(
                _clamp(
                    datos.get("max_travel_km_per_day"),
                    1.0,
                    500.0,
                    25.0,
                    notes,
                    "max_travel_km",
                )
                if datos.get("max_travel_km_per_day") is not None
                else None
            ),
            mode=datos.get("mode")
            if datos.get("mode") in ("driving", "walking")
            else "driving",
            preferred_categories=preferidas,
            avoided_categories=evitadas,
            must_include_categories=exigidas,
            include_meals=bool(datos.get("include_meals", True)),
            must_include_meals=_meals(datos.get("must_include_meals"), notes),
            meal_minutes=_clamp(datos.get("meal_minutes"), 20, 240, 90, notes, "meal_minutes"),
            # Sin numero se deja en None y manda el reloj. _clamp necesita un
            # valor por defecto, asi que la ausencia se resuelve antes.
            max_stops_per_day=(
                _clamp(datos.get("max_stops_per_day"), 1, 12, 5, notes, "max_stops_per_day")
                if datos.get("max_stops_per_day") is not None
                else None
            ),
            day_modes=_day_modes(datos.get("day_modes"), notes),
            category_minutes=_category_minutes(datos.get("category_minutes"), notes),
            # Van tambien en la peticion y no solo en la interpretacion: es lo
            # que el cliente devuelve al pedir una revision, y sin ellos el dia
            # rehecho pierde su ancla.
            must_include_place_ids=[lugar.id for lugar in pedidos],
            place_minutes=dict(minutos_por_lugar),
            start_place_id=partida.id if partida is not None else None,
            return_to_start=bool(datos.get("return_to_start", False)),
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
        must_include_places=pedidos,
        start_place=partida,
        return_to_start=bool(datos.get("return_to_start", False)),
        unmapped=unmapped,
        notes=notes,
    )


# --------------------------------------------------------------------------
# Revision de un dia
# --------------------------------------------------------------------------

REVISION_PROMPT = """\
Sos el traductor de un planificador de viajes por El Salvador. La persona ya \
tiene un itinerario y quiere cambiar UN dia.

Respondes UNICAMENTE con un objeto JSON, sin texto antes ni despues y sin \
marcas de bloque de codigo.

Cada campo es un CAMBIO. Pone null en todo lo que la persona no pidio tocar. \
Un valor donde no hubo pedido es un cambio que nadie pidio.

- "earliest_start": "HH:MM" o null. Hora minima de inicio de ese dia.
- "latest_end": "HH:MM" o null.
- "max_travel_km_per_day": numero o null. "mucho carro" o "menos manejo" es \
bajarlo bastante; "no me importa manejar" es subirlo.
- "max_stops_per_day": entero de 1 a 12, o null. "muy cargado" es bajarlo; \
"le falta" es subirlo.
- "preferred_categories": lista de "food", "nature", "culture", "viewpoint", \
"attraction", "lodging", o null.
- "avoided_categories": la misma lista, o null.
- "include_meals": booleano o null.
- "must_include_meals": lista con "lunch" y/o "dinner", o null. Las comidas \
que nombra para ese dia.
- "meal_minutes": entero de 20 a 240, o null. Minutos por comida. "dame mas \
tiempo para almorzar" es subirlo.
- "category_minutes": objeto de categoria a minutos, o null. "mas rato en el \
parque" es {"nature": 120}.
- "remove": lista con los nombres de las paradas de ESE dia que la persona \
quiere sacar, copiados tal cual de la lista que se te da. Lista vacia si no \
pidio sacar ninguna.
- "unmapped": lista de strings con lo que entendiste y no pudiste representar.

NUNCA fuerces algo dentro de un campo porque se parece. El presupuesto no \
existe como campo: si dice que un dia "se ve caro", eso va a "unmapped". \
Tampoco inventes nombres en "remove": solo los de la lista dada."""


@dataclass
class Revision:
    """Los cambios pedidos para un dia."""

    changes: dict = field(default_factory=dict)
    remove: list[str] = field(default_factory=list)
    unmapped: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def touches_anything(self) -> bool:
        return bool(self.changes or self.remove)


def _revision_context(paradas: list[str]) -> str:
    lista = "\n".join(f"- {nombre}" for nombre in paradas)
    return f"Paradas de ese dia:\n{lista}"


def interpret_revision(frase: str, stops: list[str], client=None) -> Revision:
    """Traduce un pedido de cambio sobre un dia ya armado.

    No toca la base: los nombres a sacar se resuelven contra las paradas que
    ese dia ya tiene, que es la unica lista donde tiene sentido buscarlos.
    """
    frase = (frase or "").strip()
    if not frase:
        return Revision(error="hace falta que digas que querés cambiar")
    if len(frase) > MAX_PHRASE_LENGTH:
        return Revision(
            error=f"el pedido es muy largo, el máximo son {MAX_PHRASE_LENGTH} caracteres"
        )

    if client is None:
        try:
            client = _default_client()
        except InterpretError as exc:
            return Revision(error=str(exc))

    try:
        respuesta = client.messages.create(
            model=settings.planner_model,
            max_tokens=1024,
            system=REVISION_PROMPT,
            messages=[{"role": "user", "content": f"{_revision_context(stops)}\n\n{frase}"}],
        )
        texto = "".join(b.text for b in respuesta.content if getattr(b, "type", "") == "text")
        datos = json.loads(_clean_json(texto))
    except json.JSONDecodeError:
        return Revision(error="el modelo no devolvió JSON válido")
    except Exception as exc:  # noqa: BLE001
        logger.warning("fallo interpretando la revision: %s", exc)
        return Revision(error="no se pudo interpretar el cambio")

    if not isinstance(datos, dict):
        return Revision(error="el modelo devolvió algo que no es un objeto")

    notes: list[str] = []
    cambios: dict = {}

    if datos.get("earliest_start") is not None:
        cambios["earliest_start"] = _parse_time(
            datos["earliest_start"], time(9, 0), notes, "earliest_start"
        )
    if datos.get("latest_end") is not None:
        cambios["latest_end"] = _parse_time(
            datos["latest_end"], time(20, 0), notes, "latest_end"
        )
    if datos.get("max_travel_km_per_day") is not None:
        cambios["max_travel_km_per_day"] = _clamp(
            datos["max_travel_km_per_day"], 1.0, 500.0, 25.0, notes, "max_travel_km"
        )
    if datos.get("max_stops_per_day") is not None:
        cambios["max_stops_per_day"] = _clamp(
            datos["max_stops_per_day"], 1, 12, 5, notes, "max_stops_per_day"
        )
    if datos.get("preferred_categories") is not None:
        cambios["preferred_categories"] = _categories(
            datos["preferred_categories"], notes, "preferred"
        )
    if datos.get("avoided_categories") is not None:
        cambios["avoided_categories"] = _categories(
            datos["avoided_categories"], notes, "avoided"
        )
    if isinstance(datos.get("include_meals"), bool):
        cambios["include_meals"] = datos["include_meals"]
    if datos.get("must_include_meals") is not None:
        cambios["must_include_meals"] = _meals(datos["must_include_meals"], notes)
    if datos.get("meal_minutes") is not None:
        cambios["meal_minutes"] = _clamp(
            datos["meal_minutes"], 20, 240, 90, notes, "meal_minutes"
        )
    if datos.get("category_minutes") is not None:
        cambios["category_minutes"] = _category_minutes(datos["category_minutes"], notes)

    # Solo se aceptan nombres que existan en ese dia. Un nombre inventado se
    # descarta con aviso: sacar "el museo" de un dia que no tiene museo no es
    # una operacion silenciosa, es un malentendido.
    conocidos = {n.strip().lower(): n for n in stops}
    remove: list[str] = []
    for pedido in _strings(datos.get("remove")):
        exacto = conocidos.get(pedido.lower())
        if exacto:
            remove.append(exacto)
            continue
        parecidos = [orig for clave, orig in conocidos.items() if pedido.lower() in clave]
        if len(parecidos) == 1:
            remove.append(parecidos[0])
        else:
            notes.append(f"no hay ninguna parada llamada {pedido!r} en ese día")

    return Revision(
        changes=cambios,
        remove=remove,
        unmapped=_strings(datos.get("unmapped")),
        notes=notes,
    )
