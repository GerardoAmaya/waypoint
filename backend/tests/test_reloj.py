"""Tests del reloj local.

Lo que se prueba es la zona, no la hora: que "hoy" sea el hoy de El Salvador y
no el del servidor. El fallo que esto atiende aparece entre las 18:00 y la
medianoche, cuando en UTC ya es otro dia.
"""

from datetime import UTC, date, datetime, timedelta

from app.core.reloj import TZ_EL_SALVADOR, ahora, dia_semana, en_palabras, hoy


class TestZona:
    def test_son_seis_horas_menos_que_utc(self):
        assert ahora().utcoffset() == timedelta(hours=-6)

    def test_no_hay_horario_de_verano(self):
        """El desplazamiento fijo solo es correcto si no cambia en el año."""
        offsets = {
            datetime(2026, mes, 15, tzinfo=TZ_EL_SALVADOR).utcoffset() for mes in range(1, 13)
        }
        assert offsets == {timedelta(hours=-6)}

    def test_de_noche_hoy_no_es_el_dia_siguiente(self):
        """El fallo concreto: a las 19:00 de El Salvador, en UTC ya es mañana."""
        instante = datetime(2026, 9, 11, 19, 0, tzinfo=TZ_EL_SALVADOR)

        assert instante.astimezone(UTC).date() == date(2026, 9, 12)
        assert instante.date() == date(2026, 9, 11)

    def test_hoy_es_la_fecha_de_ahora(self):
        assert hoy() == ahora().date()


class TestEnPalabras:
    def test_dice_el_dia_el_numero_y_el_mes(self):
        assert en_palabras(date(2026, 9, 11)) == "viernes 11 de septiembre"

    def test_el_lunes_es_el_primero_de_la_semana(self):
        """weekday() cuenta desde el lunes; la tabla tiene que ir igual."""
        assert dia_semana(date(2026, 9, 7)) == "lunes"
        assert dia_semana(date(2026, 9, 13)) == "domingo"
