"""Los datos derivados de las etiquetas de OSM.

OSM es texto libre escrito por miles de personas: el mismo dato llega con
prefijo y sin el, con unidades y sin ellas, y con varios valores en una sola
etiqueta separados por punto y coma. Estos tres derivadores existen para que
esa variedad no llegue al cliente, y estos tests para que sigan aguantandola.
"""

import pytest

from app.services.places import altitud_m, cocina_legible, contacto, nombre_legible


@pytest.mark.parametrize(
    "crudo,esperado",
    [
        ("pupusa", "pupusas"),
        ("steak_house", "carnes"),
        # Lo concreto manda sobre lo generico, en cualquier orden.
        ("regional;pupusa", "pupusas"),
        ("pupusa;regional", "pupusas"),
        # Generico a secas si es lo unico que hay.
        ("regional", "comida típica"),
        ("regional;fusion", "comida típica"),
        # Coma en vez de punto y coma: OSM trae las dos.
        ("sushi,japanese", "sushi"),
        # Lo que no se sabe traducir no se muestra: el valor crudo de OSM
        # delata la fuente y no ayuda a elegir donde comer.
        ("fusion", None),
        ("", None),
    ],
)
def test_cocina(crudo, esperado):
    assert cocina_legible({"cuisine": crudo}) == esperado


def test_cocina_sin_etiquetas():
    assert cocina_legible(None) is None
    assert cocina_legible({}) is None


@pytest.mark.parametrize(
    "crudo,esperado",
    [
        ("1965", 1965),
        ("2381 m", 2381),
        ("2381m", 2381),
        (" 1200 ", 1200),
        # El punto mas alto de El Salvador son 2.730 m: lo que pase de ahi es
        # un error de captura y no un dato.
        ("8848", None),
        ("-3", None),
        ("como 2000", None),
        ("", None),
    ],
)
def test_altitud(crudo, esperado):
    assert altitud_m({"ele": crudo}) == esperado


def test_contacto_con_y_sin_prefijo():
    assert contacto({"phone": "+503 2222-3333"}, "phone") == "+503 2222-3333"
    assert contacto({"contact:phone": "+503 2222-3333"}, "phone") == "+503 2222-3333"
    assert contacto({"website": "https://x.sv"}, "website") == "https://x.sv"


def test_contacto_se_queda_con_el_primero():
    """Varios numeros en una etiqueta. Mostrar los tres no cabe en el panel."""
    assert contacto({"phone": "+503 1111;+503 2222"}, "phone") == "+503 1111"


def test_telefonos_separados_por_coma():
    """El separador oficial es el punto y coma, pero la coma es igual de comun.

    Es el caso real de Pollo Campestre en el catalogo cargado: sin partir por
    coma se mostraban los dos numeros pegados como si fueran uno.
    """
    assert contacto({"phone": "2121-2828, 2312-7228"}, "phone") == "2121-2828"


def test_la_coma_no_parte_una_url():
    """En una direccion web la coma es un caracter valido: partir ahi la rompe."""
    url = "https://x.sv/a,b"
    assert contacto({"website": url}, "website") == url


def test_contacto_vacio():
    assert contacto(None, "phone") is None
    assert contacto({"phone": "   "}, "phone") is None


@pytest.mark.parametrize(
    "crudo,esperado",
    [
        # El caso real que aparecio en una captura, entre paradas normales.
        ("COMIDA A LA VISTA Y PUPUSERIA.", "Comida a La Vista y Pupuseria"),
        ("EL FARROBITO FELIZ.", "El Farrobito Feliz"),
        ("DON POLLO", "Don Pollo"),
        ("TAQUERIA TRES HERMANAS", "Taqueria Tres Hermanas"),
        # Los nexos van en minuscula en medio del nombre, los articulos no: el
        # articulo es parte del nombre del negocio.
        ("PUPUSERIA Y CAFE DE DON JOSE", "Pupuseria y Cafe de Don Jose"),
        ("RESTAURANTE EL AMATE", "Restaurante El Amate"),
        # Espacios de sobra y puntuacion final.
        ("Parque  Nacional El Imposible", "Parque Nacional El Imposible"),
        ("Mirador El Mulo.", "Mirador El Mulo"),
        # Lo que ya esta bien no se toca.
        ("Cerro Las Ninfas", "Cerro Las Ninfas"),
        ("Mercado Municipal Nº 2", "Mercado Municipal Nº 2"),
    ],
)
def test_nombre_legible(crudo, esperado):
    assert nombre_legible(crudo) == esperado


@pytest.mark.parametrize("sigla", ["ISEADE-FEPADE", "ANDEN", "UCA"])
def test_una_palabra_sola_en_mayusculas_no_se_toca(sigla):
    """Puede ser sigla, y "Iseade-Fepade" es peor que dejarla como esta."""
    assert nombre_legible(sigla) == sigla


def test_una_sigla_dentro_del_nombre_se_conserva():
    """Sin vocales no es palabra: SV se queda, DON no.

    La longitud sola no distinguia: "DON" tiene tres letras y es una palabra.
    """
    assert nombre_legible("HOTEL SV PLAZA") == "Hotel SV Plaza"


def test_el_nexo_manda_sobre_la_sigla():
    """La "Y" no tiene vocales y la prueba de sigla la daba por buena."""
    assert nombre_legible("CAFE Y PAN") == "Cafe y Pan"


def test_un_nombre_que_queda_vacio_devuelve_el_original():
    assert nombre_legible("...") == "..."
