"""Tests del nomenclator de zonas.

Las coordenadas no se comprueban aqui: CI no tiene el catalogo cargado. Para
eso esta scripts/check_zones.py, que cuenta cuantos lugares hay alrededor de
cada punto. Una zona con el punto mal no tiene lugares y se nota enseguida.
"""

import pytest

from app.services.geocode import FOTOS, ZONES, find_zone, zone_names


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


class TestAnclaDelCatalogo:
    """Un centro de viaje tiene que ser un destino.

    El caso real: "hospedaje cerca de La Gran Via" centro un viaje de tres dias
    en "Pizza Hut La Gran Via". El local se llama como la zona y gano la
    busqueda por nombre.
    """

    def _hit(self, nombre, categoria, lat=13.67, lon=-89.24):
        import uuid

        from app.services.places import PlaceHit

        return PlaceHit(
            id=uuid.uuid4(),
            name=nombre,
            category=categoria,
            subcategory=None,
            lat=lat,
            lon=lon,
            quality_score=0.7,
        )

    def _resolver(self, monkeypatch, hits):
        from app.services import geocode

        monkeypatch.setattr(geocode, "search_by_name", lambda *a, **k: hits)
        # Estos casos son sobre el ancla de punto de interes, asi que el
        # nomenclator se aisla: si no, resolveria "La Gran Via" por su cuenta y
        # el test dejaria de comprobar lo que dice comprobar.
        monkeypatch.setattr(geocode, "find_place_name", lambda *a, **k: None)
        return geocode.resolve_area(None, "La Gran Via")

    def test_descarta_un_restaurante_como_centro(self, monkeypatch):
        hits = [self._hit("Pizza Hut La Gran Via", "food")]
        assert self._resolver(monkeypatch, hits) is None

    def test_descarta_un_hotel_como_centro(self, monkeypatch):
        hits = [self._hit("Hotel La Gran Via", "lodging")]
        assert self._resolver(monkeypatch, hits) is None

    def test_prefiere_el_destino_aunque_el_negocio_coincida_mejor(self, monkeypatch):
        hits = [
            self._hit("Pizza Hut La Gran Via", "food"),
            self._hit("Mirador La Gran Via", "viewpoint"),
        ]
        resultado = self._resolver(monkeypatch, hits)

        assert resultado is not None
        assert resultado.name == "Mirador La Gran Via"
        assert resultado.source == "catalog"

    def test_un_lugar_puntual_de_verdad_si_ancla(self, monkeypatch):
        from app.services import geocode

        hits = [self._hit("Volcan de Izalco", "nature", 13.81, -89.63)]
        monkeypatch.setattr(geocode, "search_by_name", lambda *a, **k: hits)

        resultado = geocode.resolve_area(None, "el volcan ese de Izalco")

        assert resultado is not None
        assert resultado.source in {"zone", "catalog"}

    def test_el_nomenclator_sigue_mandando(self, monkeypatch):
        """Aunque el catalogo tenga algo mas parecido, la zona gana."""
        from app.services import geocode

        monkeypatch.setattr(
            geocode, "search_by_name", lambda *a, **k: [self._hit("Bar Suchitoto", "food")]
        )
        resultado = geocode.resolve_area(None, "Suchitoto")

        assert resultado is not None
        assert resultado.source == "zone"
        assert resultado.name == "Suchitoto"


def test_las_zonas_con_foto_traen_credito_completo():
    """Una foto de Commons sin autor ni licencia no se puede publicar.

    El schema ya obliga los campos, pero nada impide dejarlos en blanco. Este
    test es la garantia de que no se cuela una foto sin credito, que es un
    incumplimiento de licencia y no un detalle de estilo.
    """
    con_foto = [z for z in ZONES if z.photo is not None]

    # Si esto baja, alguien borro fotos sin querer.
    assert len(con_foto) >= 18

    for zona in con_foto:
        assert zona.photo.file, f"{zona.key}: foto sin archivo"
        assert zona.photo.author.strip(), f"{zona.key}: foto sin autor"
        assert zona.photo.license.strip(), f"{zona.key}: foto sin licencia"
        assert zona.photo.page.startswith("https://commons.wikimedia.org/"), (
            f"{zona.key}: la pagina del credito tiene que apuntar a Commons"
        )
        # Un archivo de mapa en vez de una foto: es el error que ya ocurrio una
        # vez, con el mapa de situacion del pais en lugar de Juayua.
        assert not zona.photo.file.lower().endswith(".svg"), (
            f"{zona.key}: {zona.photo.file} parece un mapa y no una foto"
        )


def test_el_area_del_catalogo_no_trae_foto():
    """Solo las zonas del nomenclator tienen identidad propia.

    Un ancla que salio de buscar por nombre es un lugar suelto del catalogo, y
    ponerle la foto de una zona vecina seria afirmar algo que no se sabe.
    """
    assert all(z.photo is None or z.key in FOTOS for z in ZONES)
    assert set(FOTOS) <= {z.key for z in ZONES}, (
        "hay fotos con claves que no corresponden a ninguna zona"
    )
