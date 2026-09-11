"""A que hora se pone el sol, calculado y no consultado.

**Es astronomia, no meteorologia, y eso cambia el diseño entero.** La primera
idea fue pedirle la puesta de sol a Open-Meteo, que la devuelve junto al clima.
Calcularla sale mejor por tres razones: no depende de que el clima este
encendido ni de que el servicio conteste, funciona mas alla de los dieciseis
dias que llega el pronostico, y no hay que esperar a la peticion de red —el
borrador del itinerario se arma antes de pedir el clima justamente para llegar
de inmediato, asi que una puesta de sol que viniera por red no estaria a tiempo
para decidir donde cabe cada parada.

El algoritmo es el de la NOAA en su forma corta. La precision que da —del orden
del minuto en estas latitudes— sobra para lo que se decide con esto, que es si
una caminata termina con luz.

**Y hacia mas falta de lo que parecia.** El motor usaba `DUSK = 18:15` fijo, con
el argumento de que en El Salvador el sol se pone entre las 17:50 y las 18:30
todo el año. Medido contra los datos reales de 2025, el rango es de **17:25 a
18:28**: en noviembre la constante mandaba gente al cerro cincuenta minutos
despues de que oscurecio, y en junio le cortaba el dia cuando todavia habia luz.
"""

from __future__ import annotations

import math
from datetime import date, time

# El dia juliano del 1 de enero del 2000 a mediodia, que es el origen que usa
# el algoritmo.
J2000 = 2451545.0

# Angulo del centro del sol bajo el horizonte al salir y al ponerse. Los -0.833
# grados son el radio aparente del disco mas la refraccion de la atmosfera: el
# sol se ve todavia cuando geometricamente ya se puso.
ANGULO_DEL_HORIZONTE = -0.833


def _dia_juliano(fecha: date) -> float:
    a = (14 - fecha.month) // 12
    y = fecha.year + 4800 - a
    m = fecha.month + 12 * a - 3
    return (
        fecha.day + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100 + y // 400 - 32045 - 0.5
    )


def _puesta_en_dias_julianos(fecha: date, lat: float, lon: float) -> float | None:
    """El instante de la puesta, o None si ese dia el sol no se pone.

    None solo ocurre dentro de los circulos polares. No pasa en El Salvador,
    pero devolverlo es mas honesto que dar una hora inventada.
    """
    # Longitud contada hacia el oeste, que es como la usa el algoritmo.
    oeste = -lon

    # Ciclo solar desde J2000, redondeado al dia.
    ciclo = round(_dia_juliano(fecha) - J2000 + 0.0009 - oeste / 360.0)

    # Mediodia solar medio: aun sin las correcciones de la orbita.
    medio = J2000 + 0.0009 + oeste / 360.0 + ciclo

    # Anomalia media del sol en su orbita.
    anomalia = math.radians((357.5291 + 0.98560028 * (medio - J2000)) % 360)

    # Ecuacion del centro: lo que la orbita se aparta de un circulo.
    centro = (
        1.9148 * math.sin(anomalia)
        + 0.0200 * math.sin(2 * anomalia)
        + 0.0003 * math.sin(3 * anomalia)
    )

    # Longitud ecliptica. El 102.9372 es el argumento del perihelio.
    ecliptica = math.radians((math.degrees(anomalia) + centro + 180 + 102.9372) % 360)

    # **Las correcciones se aplican una sola vez, sobre el mediodia medio.**
    # Aplicarlas dentro de un bucle las acumulaba y dejaba siete minutos de
    # error medio contra los datos reales, del mismo orden que el fallo que
    # esto viene a corregir.
    transito = medio + 0.0053 * math.sin(anomalia) - 0.0069 * math.sin(2 * ecliptica)

    declinacion = math.asin(math.sin(ecliptica) * math.sin(math.radians(23.4397)))

    coseno = (
        math.sin(math.radians(ANGULO_DEL_HORIZONTE))
        - math.sin(math.radians(lat)) * math.sin(declinacion)
    ) / (math.cos(math.radians(lat)) * math.cos(declinacion))

    if not -1 <= coseno <= 1:
        return None

    return transito + math.degrees(math.acos(coseno)) / 360.0


def puesta_de_sol(
    fecha: date, lat: float, lon: float, offset_horas: float = -6
) -> time | None:
    """La hora local a la que se pone el sol ese dia en ese punto.

    El desplazamiento por defecto es el de El Salvador, que no tiene horario de
    verano. Ver app/core/reloj.py, donde vive esa misma decision.
    """
    juliano = _puesta_en_dias_julianos(fecha, lat, lon)
    if juliano is None:
        return None

    # De dia juliano a fraccion del dia, ya en hora local. `_dia_juliano` ya
    # devuelve la medianoche UT de esa fecha, asi que la resta da directamente
    # la fraccion transcurrida: restarle otro medio dia la corria doce horas.
    fraccion = (juliano - _dia_juliano(fecha) + offset_horas / 24.0) % 1.0
    minutos = round(fraccion * 24 * 60)
    return time(minutos // 60 % 24, minutos % 60)
