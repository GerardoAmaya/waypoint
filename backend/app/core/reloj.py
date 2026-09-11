"""La fecha local de El Salvador.

**Existe para que "hoy" no dependa de donde este corriendo el servidor.** El
contenedor de Railway va en UTC, asi que entre las 18:00 y la medianoche de El
Salvador `date.today()` devuelve el dia siguiente. Un itinerario para "hoy" que
sale fechado manana no es un error visible en una prueba: es un error que
aparece solo de noche y en produccion.

Se usa un desplazamiento fijo y no una zona horaria con nombre porque El
Salvador no tiene horario de verano: son seis horas menos que UTC todo el año.
Asi tampoco hace falta que la imagen traiga la base de datos de zonas, que las
imagenes `slim` no incluyen.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

# UTC-6, sin horario de verano.
TZ_EL_SALVADOR = timezone(timedelta(hours=-6), "America/El_Salvador")

# Nombres de los dias para hablarle al modelo y a la persona. En minuscula
# porque en español no se escriben con mayuscula inicial.
DIAS_SEMANA = (
    "lunes",
    "martes",
    "miércoles",
    "jueves",
    "viernes",
    "sábado",
    "domingo",
)

MESES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


def ahora() -> datetime:
    """El instante actual en hora de El Salvador."""
    return datetime.now(TZ_EL_SALVADOR)


def hoy() -> date:
    """La fecha de hoy en El Salvador."""
    return ahora().date()


def dia_semana(fecha: date) -> str:
    """El nombre del dia de la semana: "sábado"."""
    return DIAS_SEMANA[fecha.weekday()]


def en_palabras(fecha: date) -> str:
    """La fecha como la diria una persona: "sábado 13 de septiembre"."""
    return f"{dia_semana(fecha)} {fecha.day} de {MESES[fecha.month - 1]}"
