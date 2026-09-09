"""Tests del nomenclator de zonas.

Las coordenadas no se comprueban aqui: CI no tiene el catalogo cargado. Para
eso esta scripts/check_zones.py, que cuenta cuantos lugares hay alrededor de
cada punto. Una zona con el punto mal no tiene lugares y se nota enseguida.
"""

import pytest

from app.services.geocode import ZONES, find_zone, zone_names


class TestResolucionDeZona:
    def test_encuentra_por_nombre_exacto(self):
        assert find_zone("Suchitoto").key == "suchitoto"

    def test_ignora_acentos_y_mayusculas(self):
        """En el chat casi nadie escribe los acentos."""
        assert find_zone("AHUACHAPAN").key == "ahuachapan"
        assert find_zone("ahuachapán").key == "ahuachapan"

    def test_encuentra_dentro_de_una_frase(self):
        assert find_zone("quiero ir tres dias a Suchitoto").key == "suchitoto"

    def test_resuelve_un_alias(self):
        assert find_zone("la ruta de las flores").key == "ataco"
        assert find_zone("el volcan de Izalco").key == "cerro-verde"

    def test_entre_varias_gana_la_mas_especifica(self):
        """'playa el tunco' describe mejor lo pedido que 'tunco'."""
        assert find_zone("me quedo en playa el tunco").key == "el-tunco"

    def test_un_lugar_desconocido_no_inventa(self):
        assert find_zone("Cancun") is None
        assert find_zone("") is None

    @pytest.mark.parametrize("zona", ZONES, ids=lambda z: z.key)
    def test_cada_zona_se_encuentra_por_su_propio_nombre(self, zona):
        encontrada = find_zone(zona.name)
        assert encontrada is not None and encontrada.key == zona.key


class TestCoherenciaDeLaLista:
    def test_las_claves_no_se_repiten(self):
        claves = [z.key for z in ZONES]
        assert len(claves) == len(set(claves))

    def test_todas_caen_dentro_de_el_salvador(self):
        """Un signo cambiado en la longitud manda la zona al oceano Indico."""
        for zona in ZONES:
            assert 13.0 < zona.lat < 14.5, zona.key
            assert -90.2 < zona.lon < -87.6, zona.key

    def test_los_radios_son_utiles(self):
        for zona in ZONES:
            assert 5_000 <= zona.radius_m <= 30_000, zona.key

    def test_los_nombres_van_al_prompt(self):
        assert "Suchitoto" in zone_names()
        assert len(zone_names()) == len(ZONES)
