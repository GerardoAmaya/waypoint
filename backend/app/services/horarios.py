"""Horarios de apertura de OpenStreetMap, para los lugares de comida.

**Tres estados y no dos, que es la decision que da forma al modulo.** De los
2.717 lugares de comida del catalogo, 419 traen `opening_hours` y 362 en un
formato utilizable: el 87% no dice nada. Con dos estados hay que elegir entre
dos errores grandes — dar por cerrado lo desconocido vacia los itinerarios, y
darlo por abierto es exactamente lo que el motor hace hoy, que es sentarte en
un comedor que no abre. Asi que se distingue ABIERTO de DESCONOCIDO, y el motor
usa la diferencia: **nunca coloca uno que sabe cerrado, y prefiere el que sabe
abierto sobre el que no sabe.**

**El parser va contra los datos, no contra la especificacion.** La gramatica de
`opening_hours` es enorme y casi nada de ella aparece en El Salvador. Lo que si
aparece, medido sobre los 419 valores reales:

    Mo-Su 10:00-22:00                       el caso comun
    24/7                                    11 casos
    Mo-Sa 06:00-19:00; Su 07:00-16:00       varias reglas
    Fr-Sa 08:00-21:00; Mo-Th,Su 08:00-20:30 listas de dias
    Mo-Fr 12:00-15:00, 17:30-22:00          dos turnos
    Tu-Su 07:00-22:00; Mo off               un dia cerrado
    Sa 11:00-01:00                          cruza la medianoche
    18:00-22:00                             sin dias: todos
    Mo 12:00‑22:00                          con guion Unicode U+2011

Y lo que no se entiende se devuelve como no entendido, sin adivinar: `Tu-Sa`
sin horas, `sunrise-sunset`, `16:00.23:00` con un punto por guion, y los
horarios escritos en prosa. Un horario mal leido es peor que uno ausente,
porque el ausente no cierra ninguna puerta y el mal leido si.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass
from datetime import date, time

MINUTOS_POR_DIA = 24 * 60
MINUTOS_POR_SEMANA = 7 * MINUTOS_POR_DIA

# Lunes es 0, igual que date.weekday().
DIAS = {
    "mo": 0,
    "tu": 1,
    "we": 2,
    "th": 3,
    "fr": 4,
    "sa": 5,
    "su": 6,
}

# Guiones que no son el guion ASCII y aparecen en el dato real: el de no
# separacion (U+2011), el corto, el largo y el menos.
GUIONES = str.maketrans({"‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-"})

_FRANJA = re.compile(r"^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})$")
_DIA = re.compile(r"^(mo|tu|we|th|fr|sa|su)$")
_RANGO_DIAS = re.compile(r"^(mo|tu|we|th|fr|sa|su)\s*-\s*(mo|tu|we|th|fr|sa|su)$")


class Apertura(enum.Enum):
    """Lo que se sabe de un lugar a una hora dada."""

    ABIERTO = "abierto"
    CERRADO = "cerrado"
    DESCONOCIDO = "desconocido"


@dataclass(frozen=True)
class Horario:
    """Los minutos de la semana en que un lugar esta abierto.

    Se guarda como intervalos de minutos desde el lunes a las 00:00 en vez de
    como dias y horas: asi un horario que cruza la medianoche —"Sa
    11:00-01:00", que existe en el dato— es un intervalo continuo y no un caso
    especial que haya que recordar en cada consulta.
    """

    intervalos: tuple[tuple[int, int], ...] = ()

    @property
    def vacio(self) -> bool:
        return not self.intervalos

    def abierto_en(self, momento: int) -> bool:
        """Si esta abierto en ese minuto de la semana."""
        momento %= MINUTOS_POR_SEMANA
        for inicio, fin in self.intervalos:
            if inicio <= momento < fin:
                return True
            # El intervalo que se sale de la semana se comprueba tambien al
            # principio: el sabado a la una de la madrugada es el minuto 60 de
            # la semana, no el 10.500.
            if fin > MINUTOS_POR_SEMANA and momento < fin - MINUTOS_POR_SEMANA:
                return True
        return False

    def cubre(self, desde: int, hasta: int) -> bool:
        """Si esta abierto durante TODO el rango, punta a punta.

        **Se exige el rango completo y no solo la llegada.** La pregunta que
        hace el motor no es "¿puedo entrar?" sino "¿me da para comer aca?", y
        un comedor que cierra a las 14:00 no sirve para sentarse a las 13:42 si
        la comida dura noventa minutos. Entrar y que te levanten no es comer.
        """
        if self.vacio or hasta < desde:
            return False
        # Basta comprobar minuto a minuto los bordes de los intervalos, pero a
        # esta escala —una semana— recorrer de diez en diez es igual de rapido
        # y mucho mas facil de leer. El paso divide a los cinco minutos, que es
        # la granularidad mas fina del dato.
        momento = desde
        while momento < hasta:
            if not self.abierto_en(momento):
                return False
            momento += 5
        return self.abierto_en(hasta - 1) if hasta > desde else True


SIEMPRE = Horario(((0, MINUTOS_POR_SEMANA),))


def minuto_de_la_semana(fecha: date, hora: time) -> int:
    """El minuto de la semana de una fecha y hora concretas."""
    return fecha.weekday() * MINUTOS_POR_DIA + hora.hour * 60 + hora.minute


def parse(texto: str | None) -> Horario | None:
    """Lee un `opening_hours`, o devuelve None si no se entiende.

    None es "no se sabe" y no "cerrado": son estados distintos y el motor los
    trata distinto. Ver la cabecera del modulo.
    """
    if not texto or not isinstance(texto, str):
        return None

    limpio = texto.translate(GUIONES).strip().lower()
    if not limpio:
        return None

    if limpio in ("24/7", "24 hours", "24/7; ph off"):
        return SIEMPRE

    # **Las reglas se sustituyen, no se suman, y confundirlo daba horarios
    # falsos.** En `opening_hours` una regla posterior manda sobre las
    # anteriores en los dias que nombra. El caso del catalogo que lo destapo es
    # "Tu-Su 13:00-20:30; We off": sumando, el `off` no aporta intervalos y el
    # miercoles se quedaba abierto por la primera regla. Sustituyendo, la
    # segunda vacia el miercoles, que es lo que dice.
    por_dia: dict[int, list[tuple[int, int]]] = {}
    algo_entendido = False

    for regla in _reglas(limpio):
        leida = _leer_regla(regla)
        if leida is None:
            # **Una regla ilegible se salta; no vuelve desconocido el horario
            # entero.** Se considero lo contrario, porque saltarla puede dar un
            # cierre falso: si la regla que no se entiende era la que abria el
            # viernes, el viernes sale cerrado. Pero los dos fallos no pesan
            # igual. Un cierre falso descarta un comedor que abria y se pierde
            # una opcion; una apertura falsa sienta a alguien en uno cerrado, y
            # eso se descubre frente a la puerta. Es la misma regla que el resto
            # del proyecto —se dice, no se sustituye— y por eso se prefiere
            # conservar lo que si se entendio.
            #
            # El caso que lo puso a prueba era un hueco del lector y se arreglo
            # ahi: ver el separador de dias por espacio en _leer_dias.
            continue
        algo_entendido = True
        dias, franjas = leida
        for dia in dias:
            por_dia[dia] = list(franjas)

    if not algo_entendido:
        return None

    intervalos = [
        (dia * MINUTOS_POR_DIA + inicio, dia * MINUTOS_POR_DIA + fin)
        for dia, franjas in por_dia.items()
        for inicio, fin in franjas
    ]
    return Horario(tuple(sorted(set(intervalos))))


def _reglas(texto: str) -> list[str]:
    """Parte el horario en reglas.

    **La coma es ambigua en el dato real y hay que desambiguarla.** Despues de
    una franja horaria significa otro turno del mismo dia —"Mo-Fr 12:00-15:00,
    17:30-22:00"— y delante de un dia significa otra regla —"Mo 17:00-21:00,Tu
    11:30-21:00". Se corta solo en las comas del segundo tipo, que son las que
    van seguidas de un nombre de dia.
    """
    partes: list[str] = []
    for trozo in texto.split(";"):
        # Corta antes de una coma que va seguida de un dia de la semana.
        for regla in re.split(r",(?=\s*(?:mo|tu|we|th|fr|sa|su)\b)", trozo):
            regla = regla.strip()
            if regla:
                partes.append(regla)
    return partes


def _leer_regla(regla: str) -> tuple[list[int], list[tuple[int, int]]] | None:
    """Una regla, como los dias que nombra y las franjas que les pone.

    Devuelve los dias aparte de las franjas porque quien llama necesita saber
    QUE dias toca la regla, no solo cuando abre: una regla `off` no aporta
    ninguna franja y aun asi tiene que poder cerrar su dia.
    """
    # Separa la parte de dias de la parte de horas: la primera franja empieza
    # con un digito.
    corte = re.search(r"\d{1,2}:\d{2}", regla)

    if corte is None:
        # Sin horas: solo vale si dice explicitamente que cierra. "Mo off" es
        # una regla que se entiende y cierra el lunes; "Tu-Sa" a secas no dice
        # ni cuando abre ni que no abra, asi que no se entiende.
        if not (regla.endswith("off") or regla.endswith("closed")):
            return None
        dias = _leer_dias(regla.rsplit(" ", 1)[0].strip() if " " in regla else "")
        return (dias, []) if dias is not None else None

    texto_dias = regla[: corte.start()].strip().rstrip(",").strip()
    texto_horas = regla[corte.start() :].strip()

    dias = _leer_dias(texto_dias)
    if dias is None:
        return None

    franjas = _leer_franjas(texto_horas)
    if not franjas:
        return None

    return dias, franjas


def _leer_dias(texto: str) -> list[int] | None:
    """Los dias de una regla. Sin dias son todos, que es lo que dice la spec."""
    if not texto:
        return list(range(7))

    dias: list[int] = []
    # El espacio separa dias igual que la coma. Es un solo caso del catalogo
    # —"Tu-Th 09:00-20:00; Fr Sa 09:00-21:00; Su 10:00-21:00"— y hacia falta
    # arreglarlo porque el fallo iba en la direccion mala: sin esto la regla del
    # viernes y el sabado no se entendia, se saltaba, y el lugar quedaba
    # declarado CERRADO esos dos dias teniendo el horario escrito.
    for parte in re.split(r"[,\s]+", texto):
        parte = parte.strip()
        if not parte:
            continue

        rango = _RANGO_DIAS.match(parte)
        if rango:
            desde, hasta = DIAS[rango.group(1)], DIAS[rango.group(2)]
            # "Fr-Su" y "Sa-Tu" son los dos validos: el segundo da la vuelta a
            # la semana, y son los fines de semana largos del dato real.
            n = desde
            while True:
                dias.append(n)
                if n == hasta:
                    break
                n = (n + 1) % 7
            continue

        suelto = _DIA.match(parte)
        if suelto:
            dias.append(DIAS[suelto.group(1)])
            continue

        # Cualquier otra cosa —"ph", "su[1]", prosa— no se adivina.
        return None

    return sorted(set(dias)) or None


def _leer_franjas(texto: str) -> list[tuple[int, int]]:
    """Las franjas horarias de una regla, en minutos desde medianoche."""
    franjas: list[tuple[int, int]] = []
    for parte in texto.split(","):
        encaja = _FRANJA.match(parte.strip())
        if not encaja:
            continue

        h1, m1, h2, m2 = (int(g) for g in encaja.groups())
        if h1 > 24 or h2 > 24 or m1 > 59 or m2 > 59:
            continue

        inicio = h1 * 60 + m1
        fin = h2 * 60 + m2

        if fin == inicio:
            continue
        if fin < inicio:
            # Cruza la medianoche: "Sa 11:00-01:00" cierra el domingo a la una.
            fin += MINUTOS_POR_DIA

        franjas.append((inicio, fin))
    return franjas


def estado(texto: str | None, fecha: date, llegada: time, salida: time) -> Apertura:
    """Si un lugar esta abierto durante toda la visita, cerrado, o no se sabe."""
    horario = parse(texto)
    if horario is None:
        return Apertura.DESCONOCIDO

    desde = minuto_de_la_semana(fecha, llegada)
    hasta = desde + _duracion(llegada, salida)
    return Apertura.ABIERTO if horario.cubre(desde, hasta) else Apertura.CERRADO


def _duracion(llegada: time, salida: time) -> int:
    minutos = (salida.hour * 60 + salida.minute) - (llegada.hour * 60 + llegada.minute)
    return minutos if minutos > 0 else 0
