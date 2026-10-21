"""Tests de guardar y leer un itinerario compartido.

Se usa una sesion falsa que lleva la cuenta de lo que se le pidio, en vez de
Postgres: lo que hay que comprobar aqui no es que el INSERT sea valido —de eso
se encarga la migracion— sino el contrato del servicio. A saber: que el codigo
no lleve caracteres que se confundan al dictarlo, que la copia guardada sepa su
propio nombre, que un choque de codigo se reintente, y sobre todo que un fallo
de la base no se lleve por delante el itinerario de quien lo pidio.
"""

import json

import pytest

from app.services import compartir


class SesionFalsa:
    """Una sesion que responde lo que se le diga y anota lo que recibio.

    `respuestas` es la cola de lo que devuelve cada SELECT de comprobacion:
    True si la fila aparecio (el INSERT entro), None si no (hubo choque).
    """

    def __init__(self, respuestas=None, revienta_en=None):
        self.respuestas = list(respuestas or [])
        self.revienta_en = revienta_en
        self.ejecutados: list[tuple[str, dict]] = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, sentencia, parametros=None):
        sql = str(sentencia)
        self.ejecutados.append((sql, parametros or {}))
        if self.revienta_en and self.revienta_en in sql:
            raise RuntimeError("la base dijo que no")
        if "INSERT" in sql or "UPDATE" in sql:
            return self
        return _Resultado(self.respuestas.pop(0) if self.respuestas else None)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class _Resultado:
    def __init__(self, valor):
        self._valor = valor

    def first(self):
        return self._valor


def sentencias(sesion, aguja):
    return [(sql, p) for sql, p in sesion.ejecutados if aguja in sql]


# --- el codigo -------------------------------------------------------------


def test_el_codigo_no_lleva_caracteres_que_se_confundan():
    """Nada de 0/O ni 1/I/l: un enlace de viaje se dicta en voz alta."""
    muestra = "".join(compartir.nuevo_codigo() for _ in range(300))
    assert not (set(muestra) & set("0O1Il"))
    assert set(muestra) <= set(compartir.ALFABETO)


def test_el_codigo_tiene_el_largo_acordado():
    assert len(compartir.nuevo_codigo()) == compartir.LARGO


def test_dos_codigos_seguidos_no_coinciden():
    assert len({compartir.nuevo_codigo() for _ in range(200)}) == 200


# --- guardar ---------------------------------------------------------------


def test_guardar_devuelve_el_codigo_que_inserto():
    sesion = SesionFalsa([True])
    codigo = compartir.guardar(sesion, lambda c: {"itinerary": {"share_code": c}})

    assert codigo is not None
    insertados = sentencias(sesion, "INSERT")
    assert len(insertados) == 1
    assert insertados[0][1]["code"] == codigo


def test_la_copia_guardada_lleva_su_propio_codigo():
    """Quien abre un enlace tiene que poder volver a compartirlo.

    Si el payload se armara antes de saber el codigo, la copia guardada no
    sabria como se llama y la pagina compartida no podria ofrecer el boton.
    """
    sesion = SesionFalsa([True])
    codigo = compartir.guardar(sesion, lambda c: {"itinerary": {"days": [], "share_code": c}})

    guardado = json.loads(sentencias(sesion, "INSERT")[0][1]["payload"])
    assert guardado["itinerary"]["share_code"] == codigo


def test_un_choque_de_codigo_se_reintenta_con_otro():
    sesion = SesionFalsa([None, True])
    codigo = compartir.guardar(sesion, lambda c: {"c": c})

    intentos = sentencias(sesion, "INSERT")
    assert len(intentos) == 2
    assert intentos[0][1]["code"] != intentos[1][1]["code"]
    assert codigo == intentos[1][1]["code"]


def test_si_nunca_hay_codigo_libre_devuelve_none_sin_lanzar():
    sesion = SesionFalsa([None] * compartir.INTENTOS)
    assert compartir.guardar(sesion, lambda c: {"c": c}) is None
    assert len(sentencias(sesion, "INSERT")) == compartir.INTENTOS


def test_si_la_base_falla_el_itinerario_sigue_llegando():
    """Compartir es un añadido: su fallo no puede tumbar el plan."""
    sesion = SesionFalsa(revienta_en="INSERT")

    assert compartir.guardar(sesion, lambda c: {"c": c}) is None
    assert sesion.rollbacks == 1


def test_si_falla_la_comprobacion_tampoco_lanza():
    """El INSERT no es el unico que puede fallar.

    La comprobacion de que la fila entro vivio un rato fuera del try, y un
    fallo ahi se escapaba hasta el stream y tumbaba el itinerario entero.
    """
    sesion = SesionFalsa([True], revienta_en="SELECT")

    assert compartir.guardar(sesion, lambda c: {"c": c}) is None
    assert sesion.rollbacks == 1


def test_guardar_no_lanza_aunque_el_payload_no_sea_serializable():
    """`default=str` existe para fechas; conviene que no se caiga sin el."""
    from datetime import date

    sesion = SesionFalsa([True])
    codigo = compartir.guardar(sesion, lambda c: {"fecha": date(2026, 10, 20)})

    assert codigo is not None
    guardado = json.loads(sentencias(sesion, "INSERT")[0][1]["payload"])
    assert guardado["fecha"] == "2026-10-20"


# --- leer ------------------------------------------------------------------


def test_leer_devuelve_el_payload_guardado():
    sesion = SesionFalsa([({"itinerary": {"days": []}},)])
    assert compartir.leer(sesion, "abc") == {"itinerary": {"days": []}}


def test_leer_un_codigo_inexistente_devuelve_none():
    sesion = SesionFalsa([None])
    assert compartir.leer(sesion, "nohay") is None
    assert sentencias(sesion, "UPDATE") == []


def test_leer_cuenta_la_apertura():
    sesion = SesionFalsa([({"a": 1},)])
    compartir.leer(sesion, "abc")

    contados = sentencias(sesion, "UPDATE")
    assert len(contados) == 1
    assert contados[0][1] == {"code": "abc"}


def test_si_no_se_puede_contar_la_apertura_el_itinerario_se_devuelve_igual():
    """La cuenta es para poder limpiar la tabla, no vale un error en pantalla."""
    sesion = SesionFalsa([({"a": 1},)], revienta_en="UPDATE")

    assert compartir.leer(sesion, "abc") == {"a": 1}
    assert sesion.rollbacks == 1


@pytest.mark.parametrize("codigo", ["", "x" * 50, "../../etc/passwd", "a'; DROP--"])
def test_leer_pasa_el_codigo_como_parametro_y_no_lo_concatena(codigo):
    sesion = SesionFalsa([None])
    compartir.leer(sesion, codigo)

    sql, parametros = sentencias(sesion, "SELECT")[0]
    assert parametros["code"] == codigo
    assert codigo not in sql or codigo == ""
