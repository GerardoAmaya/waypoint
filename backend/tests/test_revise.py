"""Tests de la revision de un dia.

Lo que hay que demostrar no es que el dia pedido cambie, sino que **los otros
no**. Un planificador que al retocar el dia 3 te mueve el 1 es peor que uno
que no deja retocar nada, porque rompe lo que ya habias aceptado.
"""

import uuid
from dataclasses import replace

import pytest

from app.models import Category
from app.services import itinerary as motor
from app.services.itinerary import BUDGET_BY_MODE, Constraints, DayState, revise_day
from app.services.places import PlaceHit


def lugar(nombre, lat, lon, categoria=Category.attraction, subcategoria="museum"):
    return PlaceHit(
        id=uuid.uuid4(),
        name=nombre,
        category=categoria.value,
        subcategory=subcategoria,
        lat=lat,
        lon=lon,
        quality_score=0.7,
    )


DESTINOS = [
    lugar("Volcan", 13.735, -89.285, Category.nature, "volcano"),
    lugar("Cascada", 13.760, -89.250, Category.nature, "waterfall"),
    lugar("Museo", 13.700, -89.220, Category.culture, "museum"),
    lugar("Teatro", 13.698, -89.191, Category.culture, "theatre"),
    lugar("Mirador", 13.710, -89.230, Category.viewpoint, "viewpoint"),
    lugar("Ruinas", 13.720, -89.240, Category.culture, "archaeological_site"),
    lugar("Cerro", 13.745, -89.265, Category.nature, "peak"),
    lugar("Termales", 13.755, -89.275, Category.attraction, "attraction"),
]
COMIDAS = [
    lugar("Comedor", 13.702, -89.222, Category.food, "restaurant"),
    lugar("Cafe", 13.706, -89.226, Category.food, "cafe"),
]
TODOS = {p.id: p for p in DESTINOS + COMIDAS}


@pytest.fixture
def catalogo(monkeypatch):
    monkeypatch.setattr(motor, "select_candidates", lambda db, c: (COMIDAS, DESTINOS))
    monkeypatch.setattr(
        motor, "places_by_ids", lambda db, ids: {i: TODOS[i] for i in ids if i in TODOS}
    )


@pytest.fixture
def restricciones():
    return Constraints(
        days=3,
        center_lat=13.72,
        center_lon=-89.24,
        max_travel_km_per_day=80,
        include_meals=False,
        max_stops_per_day=2,
    )


def estado():
    """Tres dias con dos paradas cada uno, como los tendria el cliente."""
    return [
        DayState(1, [(DESTINOS[0].id, None), (DESTINOS[1].id, None)]),
        DayState(2, [(DESTINOS[2].id, None), (DESTINOS[3].id, None)]),
        DayState(3, [(DESTINOS[4].id, None), (DESTINOS[5].id, None)]),
    ]


def nombres_por_dia(itinerario):
    return {d.number: [s.place.name for s in d.stops] for d in itinerario.days}


class TestLosOtrosDiasNoSeMueven:
    def test_conserva_las_paradas_de_los_dias_no_pedidos(self, catalogo, restricciones):
        antes = nombres_por_dia(revise_day(None, restricciones, estado(), target=3).itinerary)

        assert antes[1] == ["Volcan", "Cascada"]
        assert antes[2] == ["Museo", "Teatro"]

    def test_conserva_tambien_los_horarios(self, catalogo, restricciones):
        resultado = revise_day(None, restricciones, estado(), target=3)
        dia1 = next(d for d in resultado.itinerary.days if d.number == 1)

        assert dia1.start == restricciones.earliest_start

    def test_el_dia_pedido_si_cambia(self, catalogo, restricciones):
        """Con menos paradas permitidas, el dia 3 tiene que encogerse."""
        apretado = Constraints(
            days=1,
            center_lat=13.72,
            center_lon=-89.24,
            max_travel_km_per_day=80,
            include_meals=False,
            max_stops_per_day=1,
        )
        resultado = revise_day(
            None, restricciones, estado(), target=3, day_constraints=apretado
        )

        por_dia = nombres_por_dia(resultado.itinerary)
        assert len(por_dia[3]) == 1
        assert por_dia[1] == ["Volcan", "Cascada"], "el dia 1 no se toca"


class TestSinRepetirLugares:
    def test_no_reasigna_lo_que_usan_los_otros_dias(self, catalogo, restricciones):
        resultado = revise_day(None, restricciones, estado(), target=3)
        por_dia = nombres_por_dia(resultado.itinerary)

        del_dia_3 = set(por_dia[3])
        assert not del_dia_3 & set(por_dia[1])
        assert not del_dia_3 & set(por_dia[2])

    def test_puede_tomar_lo_que_estaba_sin_usar(self, catalogo, restricciones):
        """Quedaron Cerro y Termales libres: el dia rehecho puede usarlos."""
        resultado = revise_day(None, restricciones, estado(), target=3)
        del_dia_3 = set(nombres_por_dia(resultado.itinerary)[3])

        assert del_dia_3 & {"Cerro", "Termales", "Mirador", "Ruinas"}


class TestExclusiones:
    def test_un_lugar_excluido_no_vuelve(self, catalogo, restricciones):
        """El caso de 'sacá el museo': tiene que desaparecer del dia rehecho."""
        sin_cerro = {DESTINOS[6].id}
        resultado = revise_day(None, restricciones, estado(), target=3, exclude=sin_cerro)

        assert "Cerro" not in nombres_por_dia(resultado.itinerary)[3]


class TestParadasQueDesaparecieron:
    def test_informa_las_que_ya_no_estan_en_el_catalogo(self, catalogo, restricciones):
        """Un lugar desactivado por el filtro de calidad, por ejemplo.

        Se informa en vez de omitirse: la parada desaparecio del plan y el
        usuario tiene que enterarse, no descubrir que su dia tiene una menos.
        """
        fantasma = uuid.uuid4()
        con_fantasma = estado()
        con_fantasma[1].stops.append((fantasma, None))

        resultado = revise_day(None, restricciones, con_fantasma, target=3)

        assert resultado.missing == [fantasma]
        assert nombres_por_dia(resultado.itinerary)[2] == ["Museo", "Teatro"]


class TestVerificacion:
    def test_el_itinerario_revisado_se_vuelve_a_verificar(self, catalogo):
        """Las violaciones se recalculan sobre el resultado, no se arrastran."""
        estrecho = Constraints(
            days=3,
            center_lat=13.72,
            center_lon=-89.24,
            max_travel_km_per_day=1,
            include_meals=False,
            max_stops_per_day=2,
        )
        resultado = revise_day(None, estrecho, estado(), target=3)

        assert any(
            v.constraint == "max_travel_km_per_day" for v in resultado.itinerary.violations
        )


CASA = lugar("Casa", 13.720, -89.240, Category.lodging, "hotel")
TODOS[CASA.id] = CASA


class TestLaRevisionNoPierdeLasRestriccionesDelDia:
    """Rehacer un dia no es rehacerlo con otras reglas.

    El dia objetivo se repartia como "dia 1" de un itinerario de un dia, y el
    dia 1 de {2: "walking"} va en coche: el dia a pie se reconstruia con la
    red y con el presupuesto del coche. Solo se notaba al verificarlo, porque
    validate() si miraba el modo del dia de verdad.
    """

    # Una cadena de lugares separados: con presupuesto de coche caben los
    # cuatro y el dia pasa de veinte kilometros; con el de a pie, no.
    LEJOS = [
        lugar("Uno", 13.700, -89.220, Category.culture, "museum"),
        lugar("Dos", 13.740, -89.220, Category.culture, "theatre"),
        lugar("Tres", 13.780, -89.220, Category.nature, "waterfall"),
        lugar("Cuatro", 13.820, -89.220, Category.nature, "volcano"),
    ]

    @pytest.fixture
    def catalogo_disperso(self, monkeypatch):
        todos = {p.id: p for p in self.LEJOS}
        monkeypatch.setattr(motor, "select_candidates", lambda db, c: ([], self.LEJOS))
        monkeypatch.setattr(
            motor, "places_by_ids", lambda db, ids: {i: todos[i] for i in ids if i in todos}
        )

    def _restricciones(self, **extra):
        return Constraints(
            days=2,
            center_lat=13.75,
            center_lon=-89.22,
            max_travel_km_per_day=80,
            include_meals=False,
            max_stops_per_day=4,
            **extra,
        )

    def _estado(self):
        return [
            DayState(1, [(self.LEJOS[0].id, None)]),
            DayState(2, [(self.LEJOS[1].id, None)]),
        ]

    def test_el_dia_a_pie_se_rehace_con_su_presupuesto(self, catalogo_disperso):
        restricciones = self._restricciones(day_modes={2: "walking"})

        resultado = revise_day(None, restricciones, self._estado(), target=2)
        dia = next(d for d in resultado.itinerary.days if d.number == 2)

        assert dia.travel_km <= BUDGET_BY_MODE["walking"], (
            f"el dia a pie se rehizo con {dia.travel_km} km"
        )

    def test_en_coche_el_mismo_dia_llega_mas_lejos(self, catalogo_disperso):
        """La cota de arriba no se cumple sola: sin modo por dia, ese mismo
        dia se lleva los cuatro lugares y pasa de veinte kilometros."""
        resultado = revise_day(None, self._restricciones(), self._estado(), target=2)
        dia = next(d for d in resultado.itinerary.days if d.number == 2)

        assert dia.travel_km > BUDGET_BY_MODE["walking"]

    def test_el_dia_revisado_no_viola_su_propio_presupuesto(self, catalogo_disperso):
        """Lo que el motor construye y lo que validate() reporta tienen que
        estar de acuerdo: antes construia en coche y verificaba a pie."""
        restricciones = self._restricciones(day_modes={2: "walking"})

        resultado = revise_day(None, restricciones, self._estado(), target=2)

        assert [v.constraint for v in resultado.itinerary.violations] == []


class TestElRegresoNoSeDuplica:
    """Los otros dias vienen del cliente con su regreso ya puesto.

    schedule_day comparaba el ultimo lugar con el punto de partida por
    identidad, y al reconstruir un dia desde el catalogo ese hotel es otro
    objeto con el mismo id: el regreso se agregaba encima del que ya estaba y
    el dia terminaba llegando dos veces al hotel.
    """

    @pytest.fixture
    def catalogo_de_la_base(self, monkeypatch):
        """Devuelve copias, como hace la base de datos.

        Con los mismos objetos el test no reproduce nada: la comparacion por
        identidad acierta por casualidad y el bug no aparece.
        """
        todos = {p.id: p for p in [*DESTINOS, *COMIDAS, CASA]}
        monkeypatch.setattr(motor, "select_candidates", lambda db, c: (COMIDAS, DESTINOS))
        monkeypatch.setattr(
            motor,
            "places_by_ids",
            lambda db, ids: {i: replace(todos[i]) for i in ids if i in todos},
        )

    def test_el_dia_que_no_se_toca_conserva_un_solo_regreso(self, catalogo_de_la_base):
        restricciones = Constraints(
            days=2,
            center_lat=13.72,
            center_lon=-89.24,
            max_travel_km_per_day=80,
            include_meals=False,
            max_stops_per_day=2,
            start_place=CASA,
            return_to_start=True,
        )
        # El dia 1 llega tal como lo emitio el servidor: sale de la casa,
        # visita, y vuelve.
        con_regreso = [
            DayState(1, [(CASA.id, None), (DESTINOS[0].id, None), (CASA.id, None)]),
            DayState(2, [(CASA.id, None), (DESTINOS[2].id, None), (CASA.id, None)]),
        ]

        resultado = revise_day(None, restricciones, con_regreso, target=2)
        dia1 = next(d for d in resultado.itinerary.days if d.number == 1)

        assert [s.place.name for s in dia1.stops].count("Casa") == 2


class TestLosConsejosSeRecalculan:
    """Revisar un dia borraba TODOS los consejos del itinerario.

    `revise_day` asignaba `violations` y dejaba `advice` en la lista vacia con
    que nace Itinerary. Desde el cliente eso no se ve como un campo que falta:
    se ve como si el problema se hubiera resuelto solo, en dias que nadie pidio
    tocar.
    """

    @pytest.fixture
    def con_comidas(self):
        return Constraints(
            days=3,
            center_lat=13.72,
            center_lon=-89.24,
            max_travel_km_per_day=80,
            include_meals=True,
            max_stops_per_day=2,
        )

    def test_el_consejo_de_la_comida_no_desaparece(self, catalogo, con_comidas):
        resultado = revise_day(None, con_comidas, estado(), target=3)

        assert resultado.itinerary.advice, (
            "revisar un dia dejaba el itinerario sin ningun consejo"
        )

    def test_avisa_de_la_lluvia_sobre_una_parada_al_aire_libre(self, catalogo, con_comidas):
        """El aviso de lluvia tiene que sobrevivir a una revision.

        Si no, pedir un cambio en el dia 2 hace desaparecer la advertencia del
        dia 1, que es cuando mas se necesita: el plan ya esta casi cerrado.
        """
        from datetime import date, timedelta

        from app.services.clima import ClimaDelViaje, DiaDeClima, HoraDeClima

        arranque = date(2026, 9, 22)
        # Llueve todo el dia, asi que le toca a cualquier parada que salga.
        horas = tuple(
            HoraDeClima(hora=h, lluvia_prob=90, lluvia_mm=4.0, temperatura=27.0, codigo=63)
            for h in range(24)
        )
        clima = ClimaDelViaje(
            dias={
                arranque + timedelta(days=n): DiaDeClima(
                    fecha=arranque + timedelta(days=n), horas=horas
                )
                for n in range(3)
            }
        )
        con_fecha = replace(con_comidas, start_date=arranque)

        resultado = revise_day(None, con_fecha, estado(), target=3, clima=clima)

        assert any(c.kind == "rain_outdoors" for c in resultado.itinerary.advice)

    def test_sin_clima_no_aparecen_avisos_de_clima(self, catalogo, con_comidas):
        resultado = revise_day(None, con_comidas, estado(), target=3)

        assert not any(c.kind == "rain_outdoors" for c in resultado.itinerary.advice)
