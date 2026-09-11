"""Tests del clima.

El proveedor se sustituye por uno falso que dicta el pronostico. Es la unica
forma de probar "llueve toda la tarde del lunes" sin esperar a que llueva, y
ademas deja la bateria sin red: Open-Meteo no lleva llave, asi que nada impide
que un test salga a internet si no se le pone un doble.
"""

import uuid
from datetime import date, time, timedelta

import pytest

from app.models import Category
from app.services.clima import (
    HORIZONTE_PRONOSTICO_DIAS,
    UMBRAL_MM,
    ClimaDelViaje,
    ClimaError,
    DiaDeClima,
    HoraDeClima,
    OpenMeteo,
    _parsear,
    load_forecast,
)
from app.services.itinerary import (
    Constraints,
    Day,
    Itinerary,
    Stop,
    _franjas,
    advise,
    weather_advice,
)
from app.services.places import PlaceHit

HOY = date(2026, 9, 11)


def hora(h, prob=0, mm=0.0, temp=28.0, codigo=0) -> HoraDeClima:
    return HoraDeClima(hora=h, lluvia_prob=prob, lluvia_mm=mm, temperatura=temp, codigo=codigo)


def lluviosa(h) -> HoraDeClima:
    """Una hora que pasa los dos umbrales con holgura."""
    return hora(h, prob=90, mm=4.0, codigo=63)


def dia_de(fecha, horas) -> DiaDeClima:
    return DiaDeClima(fecha=fecha, horas=tuple(horas))


def lugar(nombre, categoria=Category.viewpoint) -> PlaceHit:
    return PlaceHit(
        id=uuid.uuid4(),
        name=nombre,
        category=categoria.value,
        subcategory=None,
        lat=13.99,
        lon=-89.55,
        quality_score=0.6,
    )


def parada(nombre, llegada, salida, categoria=Category.viewpoint) -> Stop:
    return Stop(
        place=lugar(nombre, categoria),
        arrival=time(llegada, 0),
        departure=time(salida, 0),
    )


class ProveedorFalso:
    """Devuelve el pronostico que se le dicte, o revienta si se le pide."""

    def __init__(self, dias=None, falla=False):
        self.dias = dias or {}
        self.falla = falla
        self.llamadas = []

    def forecast(self, lat, lon, desde, hasta):
        self.llamadas.append((lat, lon, desde, hasta))
        if self.falla:
            raise ClimaError("el servicio no contesto")
        return self.dias


# --------------------------------------------------------------------------
# Umbrales
# --------------------------------------------------------------------------


class TestCuandoCuentaComoLluvia:
    """Decide el agua que cae, no la probabilidad declarada.

    Hubo un umbral de probabilidad del 60% ademas de este y se quito porque la
    medicion lo desmintio: tiraba el 46% de la lluvia real del pronostico. Ver
    UMBRAL_MM.
    """

    def test_probabilidad_alta_con_gotas_no_es_lluvia(self):
        """El falso positivo de verdad, y el que este umbral filtra.

        Son 79 de 640 horas medidas: probabilidad del 60% o mas con menos de un
        milimetro. Avisar de eso entrena a la persona a ignorar los avisos.
        """
        assert not hora(15, prob=90, mm=0.2).llueve

    def test_una_tormenta_de_baja_probabilidad_si_es_lluvia(self):
        """El caso real que rompio la regla vieja.

        Santa Ana, 21 de septiembre a las 13:00: codigo 95 —tormenta— con 1.8
        mm y un 33% declarado. La regla de dos condiciones lo llamaba "sin
        lluvia". Cuanto mas lejos esta el dia, mas reparte el conjunto de
        modelos la probabilidad, asi que exigirla alta apagaba la funcion justo
        en los dias que alguien planifica con tiempo.
        """
        assert hora(13, prob=33, mm=1.8, codigo=95).llueve

    def test_el_umbral_justo_cuenta(self):
        assert hora(15, prob=0, mm=UMBRAL_MM).llueve

    def test_justo_por_debajo_no(self):
        assert not hora(15, prob=100, mm=UMBRAL_MM - 0.1).llueve


class TestFranjaDeUnDia:
    def test_la_franja_incluye_las_dos_puntas(self):
        """Una parada de 15:00 a 17:00 pasa por las tres horas."""
        dia = dia_de(HOY, [lluviosa(15), lluviosa(17), hora(16)])

        horas = dia.horas_de_lluvia(time(15, 0), time(17, 0))

        assert [h.hora for h in horas] == [15, 17]

    def test_fuera_de_la_franja_no_cuenta(self):
        dia = dia_de(HOY, [lluviosa(20)])

        assert dia.horas_de_lluvia(time(9, 0), time(18, 0)) == ()

    def test_los_minutos_no_mueven_la_hora(self):
        """15:40 sigue siendo la hora 15."""
        dia = dia_de(HOY, [lluviosa(15)])

        assert dia.llueve_a_las(time(15, 40))

    def test_la_descripcion_viene_del_codigo_wmo(self):
        assert hora(15, codigo=63).descripcion == "lluvia"
        assert hora(15, codigo=95).descripcion == "tormenta"
        # Un codigo que no esta en la tabla no revienta ni miente.
        assert hora(15, codigo=71).descripcion == "sin datos"


# --------------------------------------------------------------------------
# Lectura de la respuesta
# --------------------------------------------------------------------------


class TestLecturaDeLaRespuesta:
    CUERPO = {
        "hourly": {
            "time": ["2026-09-11T14:00", "2026-09-11T15:00", "2026-09-12T15:00"],
            "precipitation_probability": [10, 85, 30],
            "precipitation": [0.0, 5.2, 0.4],
            "temperature_2m": [31.0, 27.5, 30.0],
            "weather_code": [0, 63, 2],
        }
    }

    def test_reparte_las_horas_por_dia(self):
        dias = _parsear(self.CUERPO)

        assert set(dias) == {date(2026, 9, 11), date(2026, 9, 12)}
        assert [h.hora for h in dias[date(2026, 9, 11)].horas] == [14, 15]

    def test_lee_los_cuatro_valores(self):
        dia = _parsear(self.CUERPO)[date(2026, 9, 11)]
        quince = dia.a_las(time(15, 0))

        assert (quince.lluvia_prob, quince.lluvia_mm, quince.temperatura) == (85, 5.2, 27.5)
        assert quince.descripcion == "lluvia"
        assert quince.llueve

    def test_una_serie_que_falta_no_tumba_la_lectura(self):
        """Un servicio que deja de mandar una serie da itinerario sin clima."""
        cuerpo = {
            "hourly": {
                "time": ["2026-09-11T15:00"],
                "precipitation": [5.0],
            }
        }

        dia = _parsear(cuerpo)[date(2026, 9, 11)]

        assert dia.horas[0].lluvia_mm == 5.0
        # El hueco no se rellena con una suposicion: la probabilidad que no
        # vino sale en cero y se muestra asi.
        assert dia.horas[0].lluvia_prob == 0
        # Y el aviso se da igual, porque lo decide el agua: cinco milimetros
        # mojan aunque nadie haya dicho con que confianza.
        assert dia.horas[0].llueve

    def test_una_serie_de_otro_largo_se_descarta_entera(self):
        """No se alinea a medias: eso corre los datos de hora."""
        cuerpo = {
            "hourly": {
                "time": ["2026-09-11T14:00", "2026-09-11T15:00"],
                "precipitation_probability": [90],
                "precipitation": [4.0, 4.0],
            }
        }

        dia = _parsear(cuerpo)[date(2026, 9, 11)]

        assert [h.lluvia_prob for h in dia.horas] == [0, 0]

    @pytest.mark.parametrize(
        "cuerpo", [{}, {"hourly": {}}, {"hourly": {"time": []}}, {"hourly": 3}]
    )
    def test_sin_estructura_es_un_error(self, cuerpo):
        with pytest.raises(ClimaError):
            _parsear(cuerpo)

    def test_una_marca_de_tiempo_ilegible_se_salta(self):
        cuerpo = {
            "hourly": {
                "time": ["basura", "2026-09-11T15:00"],
                "precipitation": [1.0, 4.0],
                "precipitation_probability": [90, 90],
            }
        }

        dias = _parsear(cuerpo)

        assert list(dias) == [date(2026, 9, 11)]
        assert [h.hora for h in dias[date(2026, 9, 11)].horas] == [15]


# --------------------------------------------------------------------------
# load_forecast: cuando hay clima y cuando no
# --------------------------------------------------------------------------


class TestCuandoNoHayClima:
    """Las cuatro razones, cada una con su nombre.

    Se distinguen porque el mensaje que ve la persona es distinto: "todavia no
    hay pronostico para diciembre" y "el servicio del tiempo no contesto" son
    cosas diferentes, y un solo "sin clima" las volveria la misma.
    """

    def test_sin_fecha_no_hay_a_que_dia_pedirle_el_clima(self):
        clima = load_forecast(13.9, -89.5, None, 2, HOY, ProveedorFalso())

        assert clima.reason == "sin_fecha"
        assert not clima.hay

    def test_sin_proveedor_se_dice(self):
        clima = load_forecast(13.9, -89.5, HOY, 2, HOY, None)

        assert clima.reason == "sin_proveedor"

    def test_mas_alla_del_horizonte_no_se_inventa_un_pronostico(self):
        """Quien planifica para diciembre no recibe una prediccion falsa."""
        lejano = date(2026, 12, 20)
        proveedor = ProveedorFalso()

        clima = load_forecast(13.9, -89.5, lejano, 2, HOY, proveedor)

        assert clima.reason == "fuera_de_pronostico"
        # Y no se gasta la peticion en algo que el servicio no puede responder.
        assert proveedor.llamadas == []

    def test_un_servicio_caido_no_tumba_el_itinerario(self):
        clima = load_forecast(13.9, -89.5, HOY, 2, HOY, ProveedorFalso(falla=True))

        assert clima.reason == "sin_servicio"
        assert not clima.hay

    def test_una_respuesta_vacia_cuenta_como_sin_servicio(self):
        clima = load_forecast(13.9, -89.5, HOY, 2, HOY, ProveedorFalso(dias={}))

        assert clima.reason == "sin_servicio"


class TestElHorizonte:
    def test_el_ultimo_dia_del_horizonte_entra(self):
        borde = HOY + timedelta(days=HORIZONTE_PRONOSTICO_DIAS - 1)
        proveedor = ProveedorFalso(dias={borde: dia_de(borde, [hora(15)])})

        clima = load_forecast(13.9, -89.5, borde, 1, HOY, proveedor)

        assert clima.hay

    def test_un_viaje_que_cruza_el_borde_se_pide_hasta_donde_llega(self):
        """Cinco dias con clima y dos sin el es mejor que ninguno con clima."""
        arranque = HOY + timedelta(days=HORIZONTE_PRONOSTICO_DIAS - 3)
        proveedor = ProveedorFalso(dias={arranque: dia_de(arranque, [hora(15)])})

        load_forecast(13.9, -89.5, arranque, 7, HOY, proveedor)

        _, _, desde, hasta = proveedor.llamadas[0]
        assert desde == arranque
        # Se recorta al ultimo dia que el servicio puede responder.
        assert hasta == HOY + timedelta(days=HORIZONTE_PRONOSTICO_DIAS - 1)


class TestCache:
    def test_dos_itinerarios_seguidos_gastan_una_peticion(self, monkeypatch):
        """El pronostico se renueva cada hora en el origen: pedirlo dos veces
        en el mismo minuto es gastar una peticion en recibir lo mismo."""
        llamadas = []

        def falso_pedir(self, lat, lon, desde, hasta):
            llamadas.append((lat, lon, desde, hasta))
            return {desde: dia_de(desde, [hora(15)])}

        monkeypatch.setattr(OpenMeteo, "_pedir", falso_pedir)
        proveedor = OpenMeteo()

        proveedor.forecast(13.9942, -89.5597, HOY, HOY)
        proveedor.forecast(13.9942, -89.5597, HOY, HOY)

        assert len(llamadas) == 1

    def test_unos_metros_de_diferencia_no_piden_otro_pronostico(self, monkeypatch):
        """Sin redondear, cada punto de partida pediria su propio pronostico."""
        llamadas = []
        monkeypatch.setattr(
            OpenMeteo,
            "_pedir",
            lambda self, lat, lon, desde, hasta: llamadas.append(1) or {},
        )
        proveedor = OpenMeteo()

        proveedor.forecast(13.9942, -89.5597, HOY, HOY)
        proveedor.forecast(13.9943, -89.5598, HOY, HOY)

        assert len(llamadas) == 1

    def test_otra_zona_si_pide_su_pronostico(self, monkeypatch):
        llamadas = []
        monkeypatch.setattr(
            OpenMeteo,
            "_pedir",
            lambda self, lat, lon, desde, hasta: llamadas.append(1) or {},
        )
        proveedor = OpenMeteo()

        proveedor.forecast(13.9942, -89.5597, HOY, HOY)  # Santa Ana
        proveedor.forecast(13.6929, -89.2182, HOY, HOY)  # San Salvador

        assert len(llamadas) == 2


# --------------------------------------------------------------------------
# Los avisos
# --------------------------------------------------------------------------


class TestFranjasSeguidas:
    def test_agrupa_las_horas_seguidas(self):
        assert _franjas([14, 15, 16]) == [(14, 16)]

    def test_separa_dos_chubascos(self):
        """Decir "de 14:00 a 20:00" con una tarde seca en medio es decir algo falso."""
        assert _franjas([14, 15, 19, 20]) == [(14, 15), (19, 20)]

    def test_una_hora_sola(self):
        assert _franjas([15]) == [(15, 15)]

    def test_ni_ordenadas_ni_repetidas_importan(self):
        assert _franjas([16, 14, 15, 15]) == [(14, 16)]

    def test_sin_horas_no_hay_franjas(self):
        assert _franjas([]) == []


class TestAvisoDeLluvia:
    """El aviso salta sobre lo que se puede accionar y se calla sobre el resto."""

    def _armar(self, paradas, horas_del_clima, fecha=HOY, days=1):
        itinerario = Itinerary(days=[Day(number=1, stops=paradas)])
        restricciones = Constraints(
            days=days, start_date=fecha, center_lat=13.99, center_lon=-89.55
        )
        clima = ClimaDelViaje(dias={fecha: dia_de(fecha, horas_del_clima)})
        return weather_advice(itinerario, restricciones, clima)

    def test_avisa_del_mirador_bajo_el_chubasco(self):
        consejos = self._armar(
            [parada("Cerro Verde", 15, 17)],
            [lluviosa(15), lluviosa(16), lluviosa(17)],
        )

        assert len(consejos) == 1
        assert consejos[0].kind == "rain_outdoors"
        assert consejos[0].day == 1
        assert "Cerro Verde" in consejos[0].detail
        assert "de 15:00 a 17:59" in consejos[0].detail

    def test_no_avisa_por_llover_sobre_un_museo(self):
        """Que llueva mientras se esta bajo techo no es un problema que resolver."""
        consejos = self._armar(
            [parada("Museo de Arte", 15, 17, Category.culture)],
            [lluviosa(15), lluviosa(16)],
        )

        assert consejos == []

    def test_no_avisa_por_lluvia_fuera_del_horario(self):
        """Llover a las 21:00 de un dia que termino a las 18:00 es informacion,
        no un consejo: va en la ficha del clima."""
        consejos = self._armar([parada("Cerro Verde", 10, 12)], [lluviosa(21)])

        assert consejos == []

    def test_nombra_las_dos_paradas_mojadas_en_un_solo_aviso(self):
        consejos = self._armar(
            [parada("Cerro Verde", 14, 15), parada("Lago de Coatepeque", 16, 17)],
            [lluviosa(14), lluviosa(16)],
        )

        assert len(consejos) == 1
        assert "Cerro Verde" in consejos[0].detail
        assert "Lago de Coatepeque" in consejos[0].detail
        # La concordancia sigue al numero de paradas: decia "esa parada"
        # nombrando dos.
        assert "están" in consejos[0].detail
        assert "las mueva" in consejos[0].detail

    def test_el_dia_de_ida_y_vuelta_no_nombra_el_lugar_dos_veces(self):
        mirador = lugar("Cerro Verde")
        paradas = [
            Stop(place=mirador, arrival=time(9, 0), departure=time(9, 0)),
            parada("Museo", 11, 12, Category.culture),
            Stop(place=mirador, arrival=time(15, 0), departure=time(15, 0)),
        ]

        consejos = self._armar(paradas, [lluviosa(9), lluviosa(15)])

        assert consejos[0].detail.count("Cerro Verde") == 1
        assert "está" in consejos[0].detail
        assert "mueva esa parada" in consejos[0].detail

    def test_sin_clima_no_hay_avisos_de_clima(self):
        itinerario = Itinerary(days=[Day(number=1, stops=[parada("Cerro Verde", 15, 17)])])
        restricciones = Constraints(days=1, center_lat=13.99, center_lon=-89.55)

        assert weather_advice(itinerario, restricciones, None) == []
        assert (
            weather_advice(itinerario, restricciones, ClimaDelViaje(reason="sin_fecha")) == []
        )

    def test_el_clima_de_otro_dia_no_se_le_aplica_a_este(self):
        """El dia 2 no hereda la lluvia del dia 1."""
        itinerario = Itinerary(
            days=[
                Day(number=1, stops=[parada("Cerro Verde", 15, 17)]),
                Day(number=2, stops=[parada("Lago de Coatepeque", 15, 17)]),
            ]
        )
        restricciones = Constraints(
            days=2, start_date=HOY, center_lat=13.99, center_lon=-89.55
        )
        clima = ClimaDelViaje(dias={HOY: dia_de(HOY, [lluviosa(15), lluviosa(16)])})

        consejos = weather_advice(itinerario, restricciones, clima)

        assert [c.day for c in consejos] == [1]

    def test_sin_fecha_el_motor_no_le_pone_clima_a_ningun_dia(self):
        itinerario = Itinerary(days=[Day(number=1, stops=[parada("Cerro Verde", 15, 17)])])
        restricciones = Constraints(days=1, center_lat=13.99, center_lon=-89.55)
        clima = ClimaDelViaje(dias={HOY: dia_de(HOY, [lluviosa(15)])})

        assert weather_advice(itinerario, restricciones, clima) == []


class TestElAvisoSobreviveASinComidas:
    def test_apagar_las_comidas_no_apaga_el_clima(self):
        """advise() cortaba antes de tiempo y se llevaba los dos por delante."""
        itinerario = Itinerary(days=[Day(number=1, stops=[parada("Cerro Verde", 15, 17)])])
        restricciones = Constraints(
            days=1,
            start_date=HOY,
            center_lat=13.99,
            center_lon=-89.55,
            include_meals=False,
        )
        clima = ClimaDelViaje(dias={HOY: dia_de(HOY, [lluviosa(15), lluviosa(16)])})

        consejos = advise(itinerario, restricciones, [], None, clima)

        assert [c.kind for c in consejos] == ["rain_outdoors"]


class TestLaDescripcionNoAlarmaSinMotivo:
    """El resumen decia "tormenta" en dias que no iban a llover.

    Caso real: Suchitoto el 12 de septiembre, con un codigo 95 en una sola hora
    —las 19:00, con 0.4 mm— y medio milimetro en toda la jornada. El maximo de
    los codigos se quedaba con la tormenta. Quien lee "32 grados, tormenta"
    cancela el paseo por algo que la propia respuesta dice que no va a pasar.
    """

    def test_un_codigo_de_tormenta_sin_agua_no_define_el_dia(self):
        dia = dia_de(
            HOY,
            [
                hora(15, prob=20, mm=0.0, codigo=3),
                hora(16, prob=25, mm=0.0, codigo=3),
                hora(17, prob=30, mm=0.4, codigo=95),
            ],
        )

        resumen = dia.resumen(time(15, 0), time(17, 0))

        assert resumen.descripcion == "nublado"
        assert resumen.horas_de_lluvia == ()

    def test_cuando_si_llueve_manda_el_codigo_de_las_horas_de_lluvia(self):
        dia = dia_de(
            HOY,
            [
                hora(15, prob=30, mm=0.0, codigo=3),
                hora(16, prob=80, mm=4.0, codigo=95),
            ],
        )

        resumen = dia.resumen(time(15, 0), time(16, 0))

        assert resumen.descripcion == "tormenta"
        assert resumen.horas_de_lluvia == (16,)

    def test_un_dia_de_llovizna_que_no_llega_al_umbral_se_dice_suave(self):
        """Llueve poco pero llueve: lo más suave que se puede decir."""
        dia = dia_de(
            HOY,
            [
                hora(15, prob=60, mm=0.3, codigo=51),
                hora(16, prob=65, mm=0.4, codigo=95),
            ],
        )

        resumen = dia.resumen(time(15, 0), time(16, 0))

        assert resumen.descripcion == "llovizna ligera"
        assert resumen.horas_de_lluvia == ()

    def test_la_temperatura_es_la_de_la_franja_en_que_se_viaja(self):
        """34 a las 14:00 y 21 a las 4:00 de la madrugada no describen un día
        que va de 9:00 a 18:00."""
        dia = dia_de(
            HOY,
            [hora(4, temp=21.0), hora(10, temp=28.0), hora(14, temp=34.0)],
        )

        resumen = dia.resumen(time(9, 0), time(18, 0))

        assert (resumen.temp_max, resumen.temp_min) == (34, 28)

    def test_sin_horas_dentro_de_la_franja_no_hay_resumen(self):
        dia = dia_de(HOY, [hora(3)])

        assert dia.resumen(time(9, 0), time(18, 0)) is None
