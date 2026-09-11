"""Tests del cálculo de la puesta de sol.

Los valores contra los que se compara son los del archivo histórico de
Open-Meteo para San Salvador, 2025. No son "la verdad" —también son un
cálculo— pero son una implementación independiente, y que dos coincidan es lo
más cerca de verificable que se puede estar sin salir a mirar el cielo.

Sobre 365 días y cuatro puntos del país, la diferencia media es de 2 minutos y
la máxima de 4, siempre en el mismo sentido. Se documenta y no se corrige: no
hay motivo para calibrar un cálculo contra otro, y cuatro minutos son ruido al
lado de los cincuenta que erraba la constante que esto reemplaza.
"""

from datetime import date, time

import pytest

from app.services.sol import puesta_de_sol

SAN_SALVADOR = (13.70, -89.22)

# Del archivo de Open-Meteo, San Salvador 2025. Los solsticios, los equinoccios
# y los dos extremos del año.
CONOCIDOS = [
    (date(2025, 1, 15), time(17, 48)),
    (date(2025, 3, 20), time(18, 7)),
    (date(2025, 6, 21), time(18, 26)),
    (date(2025, 9, 22), time(17, 52)),
    (date(2025, 11, 15), time(17, 26)),
    (date(2025, 12, 21), time(17, 34)),
]

# La diferencia que se acepta contra la otra implementación. Ver la cabecera.
TOLERANCIA_MINUTOS = 5


def minutos(momento: time) -> int:
    return momento.hour * 60 + momento.minute


class TestContraLosDatosReales:
    @pytest.mark.parametrize(("fecha", "esperada"), CONOCIDOS)
    def test_coincide_con_el_archivo(self, fecha, esperada):
        calculada = puesta_de_sol(fecha, *SAN_SALVADOR)

        assert abs(minutos(calculada) - minutos(esperada)) <= TOLERANCIA_MINUTOS

    def test_el_rango_del_año_es_el_medido(self):
        """De 17:25 a 18:28, no "entre las 17:50 y las 18:30".

        Ese era el argumento con el que se justificaba la constante, y estaba
        mal por la punta de abajo: en noviembre oscurece veinticinco minutos
        antes de lo que decía.
        """
        todas = [
            puesta_de_sol(date(2025, mes, dia), *SAN_SALVADOR)
            for mes in range(1, 13)
            for dia in (1, 15)
        ]

        assert min(minutos(p) for p in todas) < minutos(time(17, 35))
        assert max(minutos(p) for p in todas) > minutos(time(18, 20))

    def test_en_noviembre_oscurece_mucho_antes_que_la_constante(self):
        """El caso que motivó el cambio: la constante eran las 18:15."""
        noviembre = puesta_de_sol(date(2025, 11, 15), *SAN_SALVADOR)

        assert minutos(time(18, 15)) - minutos(noviembre) > 40

    def test_en_junio_oscurece_despues_que_la_constante(self):
        """Se equivocaba en los dos sentidos: en junio cortaba el día con luz."""
        junio = puesta_de_sol(date(2025, 6, 21), *SAN_SALVADOR)

        assert minutos(junio) > minutos(time(18, 15))


class TestBordes:
    def test_el_polo_en_invierno_no_devuelve_una_hora_inventada(self):
        """No pasa en El Salvador, pero devolver None es más honesto que
        inventar una puesta que no ocurre."""
        assert puesta_de_sol(date(2025, 12, 21), 78.0, 15.0) is None

    def test_dos_puntos_del_pais_apenas_se_diferencian(self):
        """El Salvador entero cabe en unos minutos de diferencia."""
        oriente = puesta_de_sol(date(2025, 9, 14), 13.34, -87.84)
        occidente = puesta_de_sol(date(2025, 9, 14), 13.99, -89.56)

        assert 0 < minutos(occidente) - minutos(oriente) < 15

    def test_cruzar_el_año_no_rompe_el_calculo(self):
        diciembre = puesta_de_sol(date(2025, 12, 31), *SAN_SALVADOR)
        enero = puesta_de_sol(date(2026, 1, 1), *SAN_SALVADOR)

        assert abs(minutos(diciembre) - minutos(enero)) <= 2
