"""Tests del lector de `opening_hours`.

Las cadenas que se prueban son las del catalogo, copiadas tal cual. Probar la
especificacion de OpenStreetMap seria probar un parser que nadie va a usar: lo
que importa es lo que de verdad escribieron los 419 lugares de comida que
traen horario.
"""

from datetime import date, time

import pytest

from app.services.horarios import (
    MINUTOS_POR_DIA,
    SIEMPRE,
    Apertura,
    estado,
    minuto_de_la_semana,
    parse,
)

# 2026-09-14 es lunes; 15 martes; 19 sabado; 20 domingo.
LUNES = date(2026, 9, 14)
MARTES = date(2026, 9, 15)
MIERCOLES = date(2026, 9, 16)
VIERNES = date(2026, 9, 18)
SABADO = date(2026, 9, 19)
DOMINGO = date(2026, 9, 20)


def abierto(texto, fecha, desde, hasta=None):
    """Si el lugar da para una visita entre esas dos horas."""
    fin = hasta if hasta is not None else desde
    return estado(texto, fecha, time(desde, 0), time(fin, 0))


class TestLoQueNoSeEntiende:
    """Lo ilegible es DESCONOCIDO, nunca cerrado ni una suposicion.

    Un horario mal leido es peor que uno ausente: el ausente no cierra ninguna
    puerta y el mal leido si. Estas son las 38 cadenas que el catalogo trae y
    el lector no acepta, resumidas por forma.
    """

    @pytest.mark.parametrize(
        "texto",
        [
            "sunrise-sunset",
            "Tu-Sa",
            "Lunes a Domingo : 06:00 a 13:00",
            "Lun-dom 8 a. m.-8:30 p. m.",
            "Todos los dias 10am a 8:30pm",
            "lu-do 8:00 am 10:00 pm",
            "Every Second Sunday, 10:00-16:00",
            "12 a 10 pm",
            "Cerrado Temporalmente",
            "16:00.23:00",
            "",
            None,
        ],
    )
    def test_no_se_adivina(self, texto):
        assert parse(texto) is None
        assert abierto(texto, LUNES, 12, 14) is Apertura.DESCONOCIDO

    def test_un_lugar_sin_horario_no_se_da_por_cerrado(self):
        """El 87% de la comida no trae horario. Darlo por cerrado vaciaría los
        itinerarios; darlo por abierto es lo que el motor hacía."""
        assert abierto(None, LUNES, 12, 14) is Apertura.DESCONOCIDO


class TestElCasoComun:
    """`Mo-Su 10:00-22:00` y sus variantes son 300 y pico de los 419."""

    def test_dentro_del_horario(self):
        assert abierto("Mo-Su 10:00-22:00", LUNES, 12, 14) is Apertura.ABIERTO

    def test_fuera_del_horario(self):
        assert abierto("Mo-Su 10:00-22:00", LUNES, 7, 9) is Apertura.CERRADO

    def test_el_dia_que_no_abre(self):
        assert abierto("Mo-Fr 09:00-17:00", SABADO, 12, 14) is Apertura.CERRADO
        assert abierto("Mo-Fr 09:00-17:00", VIERNES, 12, 14) is Apertura.ABIERTO

    def test_24_7_siempre_abre(self):
        assert parse("24/7") == SIEMPRE
        assert abierto("24/7", DOMINGO, 3, 5) is Apertura.ABIERTO


class TestLaVisitaEnteraONada:
    """Se exige el rango completo y no solo la llegada.

    La pregunta no es "¿puedo entrar?" sino "¿me da para comer acá?". Un
    comedor que cierra a las 14:00 no sirve para sentarse a las 13:42 si la
    comida dura noventa minutos: entrar y que te levanten no es comer.
    """

    HORARIO = "Mo-Su 11:00-14:00"

    def test_no_alcanza_con_llegar_antes_del_cierre(self):
        assert estado(self.HORARIO, LUNES, time(13, 42), time(15, 12)) is Apertura.CERRADO

    def test_si_la_visita_entra_completa_abre(self):
        assert estado(self.HORARIO, LUNES, time(12, 0), time(13, 30)) is Apertura.ABIERTO

    def test_el_borde_justo_entra(self):
        assert estado(self.HORARIO, LUNES, time(11, 0), time(14, 0)) is Apertura.ABIERTO

    def test_un_minuto_de_mas_no(self):
        assert estado(self.HORARIO, LUNES, time(11, 0), time(14, 1)) is Apertura.CERRADO


class TestVariasReglas:
    """Cadenas del catalogo con `;` y con listas de dias."""

    def test_el_domingo_con_horario_propio(self):
        horario = "Mo-Sa 06:00-19:00; Su 07:00-16:00"

        assert abierto(horario, LUNES, 6, 7) is Apertura.ABIERTO
        assert abierto(horario, DOMINGO, 6, 7) is Apertura.CERRADO
        assert abierto(horario, DOMINGO, 8, 9) is Apertura.ABIERTO

    def test_lista_de_dias_con_rango_dentro(self):
        """ "Mo-Th,Su 08:00-20:30" del catalogo."""
        horario = "Fr-Sa 08:00-21:00; Mo-Th,Su 08:00-20:30"

        assert abierto(horario, VIERNES, 20, 21) is Apertura.ABIERTO
        assert abierto(horario, LUNES, 20, 21) is Apertura.CERRADO
        assert abierto(horario, DOMINGO, 19, 20) is Apertura.ABIERTO

    def test_un_dia_marcado_off(self):
        horario = "Tu-Su 07:00-22:00; Mo off"

        assert abierto(horario, MARTES, 12, 14) is Apertura.ABIERTO
        assert abierto(horario, LUNES, 12, 14) is Apertura.CERRADO

    def test_off_en_medio_gana_sobre_el_rango(self):
        """ "Tu-Su 13:00-20:30; We off": el miércoles queda fuera."""
        horario = "Tu-Su 13:00-20:30; We off"

        assert abierto(horario, MARTES, 14, 15) is Apertura.ABIERTO
        assert abierto(horario, MIERCOLES, 14, 15) is Apertura.CERRADO

    def test_dos_turnos_en_el_mismo_dia(self):
        """ "Mo-Fr 12:00-15:00, 17:30-22:00": la coma es otro turno, no otra regla."""
        horario = "Mo-Fr 12:00-15:00, 17:30-22:00"

        assert abierto(horario, LUNES, 13, 14) is Apertura.ABIERTO
        assert abierto(horario, LUNES, 18, 19) is Apertura.ABIERTO
        # La siesta de en medio: cerrado de verdad.
        assert abierto(horario, LUNES, 16, 17) is Apertura.CERRADO

    def test_la_coma_antes_de_un_dia_es_otra_regla(self):
        """ "Mo 17:00-21:00,Tu 11:30-21:00,Su 11:30-20:30" del catálogo.

        La misma coma significa dos cosas distintas según lo que le sigue, y
        confundirlas daba un lunes abierto a mediodía que no existe.
        """
        horario = "Mo 17:00-21:00,Tu 11:30-21:00,Su 11:30-20:30"

        assert abierto(horario, LUNES, 18, 19) is Apertura.ABIERTO
        assert abierto(horario, LUNES, 12, 13) is Apertura.CERRADO
        assert abierto(horario, MARTES, 12, 13) is Apertura.ABIERTO


class TestMedianoche:
    def test_cierra_pasada_la_medianoche(self):
        """ "Sa 11:00-01:00": el sábado cierra el domingo a la una."""
        horario = "Sa 11:00-01:00"

        assert abierto(horario, SABADO, 23, 23) is Apertura.ABIERTO
        assert estado(horario, DOMINGO, time(0, 10), time(0, 40)) is Apertura.ABIERTO
        assert abierto(horario, DOMINGO, 2, 3) is Apertura.CERRADO

    def test_el_cruce_de_fin_de_semana_da_la_vuelta(self):
        """El domingo a la una de la madrugada es el minuto 60 de la semana, no
        el 10.500: sin dar la vuelta, ese intervalo se perdía."""
        horario = "Su 20:00-02:00"

        assert abierto(horario, DOMINGO, 21, 22) is Apertura.ABIERTO
        assert estado(horario, LUNES, time(0, 30), time(1, 0)) is Apertura.ABIERTO

    def test_medianoche_como_final(self):
        assert abierto("Sa-Su 13:00-00:00", SABADO, 22, 23) is Apertura.ABIERTO


class TestRarezasDelDatoReal:
    def test_el_guion_unicode_no_rompe(self):
        """ "Mo 12:00‑22:00" trae U+2011, que no es el guion ASCII."""
        assert abierto("Mo 12:00‑22:00", LUNES, 13, 14) is Apertura.ABIERTO

    def test_sin_dias_son_todos(self):
        """ "18:00-22:00" sin días: la spec dice todos los días."""
        assert abierto("18:00-22:00", LUNES, 19, 20) is Apertura.ABIERTO
        assert abierto("18:00-22:00", DOMINGO, 19, 20) is Apertura.ABIERTO
        assert abierto("18:00-22:00", LUNES, 12, 13) is Apertura.CERRADO

    def test_un_rango_de_dias_que_da_la_vuelta(self):
        """ "Sa-Tu" existe: el fin de semana largo."""
        horario = "Sa-Tu 10:00-20:00"

        assert abierto(horario, SABADO, 12, 13) is Apertura.ABIERTO
        assert abierto(horario, LUNES, 12, 13) is Apertura.ABIERTO
        assert abierto(horario, MIERCOLES, 12, 13) is Apertura.CERRADO

    def test_una_regla_ilegible_no_tumba_las_legibles(self):
        """ "Mo-Sa 08:00-18:00; Su cuando quiera" deja el sábado en pie."""
        horario = "Mo-Sa 08:00-18:00; Su cuando quiera"

        assert abierto(horario, SABADO, 12, 13) is Apertura.ABIERTO
        assert abierto(horario, DOMINGO, 12, 13) is Apertura.CERRADO

    def test_una_hora_imposible_se_descarta(self):
        assert parse("Mo 25:00-99:00") is None


class TestMinutoDeLaSemana:
    def test_el_lunes_empieza_la_semana(self):
        assert minuto_de_la_semana(LUNES, time(0, 0)) == 0

    def test_el_domingo_es_el_septimo_dia(self):
        assert minuto_de_la_semana(DOMINGO, time(0, 0)) == 6 * MINUTOS_POR_DIA
