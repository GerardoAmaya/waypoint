"""Tests de agrupar las filas que describen el mismo sitio.

El fallo que los motiva: tres días por la Ruta de las Flores metían "Parque
Nacional El Imposible" y "Parque El Imposible" el mismo día, con el almuerzo en
medio. El día gastaba 34 de sus 47 kilómetros en ir a comer y volver al mismo
parque.

**No es deduplicación y la diferencia importa.** Un duplicado es una fila
sobrante: se desactiva y desaparece. Esto agrupa filas que son todas legítimas
—la reserva y su entrada, a 1.173 metros— y las deja activas. Lo único que se
evita es visitarlas las dos en el mismo viaje.
"""

from collections import Counter

import pytest

from scripts.load_places import (
    MINIMO_PALABRA_RARA,
    _es_el_mismo_sitio,
    _frecuencia_de_palabras,
    _palabras_significativas,
)


def frecuencia(*nombres: str) -> Counter:
    return _frecuencia_de_palabras(list(nombres))


class TestPalabrasDeUnNombre:
    def test_ignora_tildes_y_mayusculas(self):
        """OpenStreetMap las pone a voluntad: "Volcan" y "Volcán" conviven."""
        assert _palabras_significativas("Volcán DE Izalco") == {"volcan", "izalco"}

    def test_ignora_articulos_y_preposiciones(self):
        """ "Cerro Nubes" y "Cerro de Nubes" son el mismo cerro."""
        assert _palabras_significativas("Cerro de Nubes") == _palabras_significativas(
            "Cerro Nubes"
        )

    def test_la_puntuacion_no_cuenta(self):
        assert _palabras_significativas('Playa Los Cóbanos ("El Privado")') == {
            "playa",
            "cobanos",
            "privado",
        }


class TestCuandoSonElMismoSitio:
    """Dos condiciones, y cada una ataja lo que la otra deja pasar."""

    def test_el_caso_del_reporte(self):
        """La reserva y su entrada, a 1.173 metros."""
        frec = frecuencia("Parque Nacional El Imposible", "Parque El Imposible")

        assert _es_el_mismo_sitio(
            "Parque Nacional El Imposible", "Parque El Imposible", frec, MINIMO_PALABRA_RARA
        )

    def test_un_nombre_tiene_que_contener_al_otro(self):
        """ "Bahía Dorada" y "Bahía Del Sol" son dos playas distintas.

        Se parecen 0,77 por trigramas —más que el caso bueno, que saca 0,69—
        así que el parecido no sirve para separarlos. La contención sí:
        "dorada" no está en el otro nombre.
        """
        frec = frecuencia("Bahia Dorada", "Bahia Del Sol")

        assert not _es_el_mismo_sitio(
            "Bahia Dorada", "Bahia Del Sol", frec, MINIMO_PALABRA_RARA
        )

    def test_dos_ruinas_numeradas_no_se_agrupan(self):
        """ "Estructura 6" y "Estructura 2" son dos construcciones del sitio."""
        frec = frecuencia("Estructura 6", "Estructura 2")

        assert not _es_el_mismo_sitio(
            "Estructura 6", "Estructura 2", frec, MINIMO_PALABRA_RARA
        )

    def test_una_palabra_comun_contenida_no_alcanza(self):
        """ "Hostel" está dentro de "Casa Frolaz Hostel" y son dos sitios.

        La contención sola los uniría. Lo que los separa es que "hostel" es una
        palabra común: aparece en diecinueve lugares del catálogo.
        """
        frec = frecuencia(*["Hostel " + str(n) for n in range(12)], "Casa Frolaz Hostel")

        assert not _es_el_mismo_sitio(
            "Hostel", "Casa Frolaz Hostel", frec, MINIMO_PALABRA_RARA
        )

    def test_una_palabra_rara_contenida_si(self):
        """Lo mismo, pero con una palabra que casi no aparece en el catálogo."""
        frec = frecuencia("Cafetalón", "Parque El Cafetalón", "Otro lugar cualquiera")

        assert _es_el_mismo_sitio(
            "Cafetalón", "Parque El Cafetalón", frec, MINIMO_PALABRA_RARA
        )

    def test_los_nombres_identicos_los_resuelve_el_motor(self):
        """Dos "Pizza Hut" a cuarenta kilómetros no son el mismo sitio.

        También sobran en un mismo viaje, pero esa es otra regla y vive en
        `_name_key`: aquí se agrupan filas del mismo lugar, no de la misma
        marca.
        """
        frec = frecuencia("Pizza Hut", "Pizza Hut")

        assert not _es_el_mismo_sitio("Pizza Hut", "Pizza Hut", frec, MINIMO_PALABRA_RARA)

    @pytest.mark.parametrize("vacio", ["", "   ", "de la"])
    def test_un_nombre_sin_palabras_utiles_no_agrupa_nada(self, vacio):
        frec = frecuencia(vacio, "Parque El Imposible")

        assert not _es_el_mismo_sitio(vacio, "Parque El Imposible", frec, MINIMO_PALABRA_RARA)
