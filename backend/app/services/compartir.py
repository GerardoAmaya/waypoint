"""Guardar un itinerario para poder abrirlo por enlace.

Hasta ahora un itinerario vivia solo en la pestaña de quien lo pidio: se podia
copiar como texto y nada mas. Para un planificador de viajes eso es raro, que
el acto siguiente a armar un plan es enseñarselo a quien va con vos.

**Lo guarda el servidor al armarlo, no el cliente al compartirlo.** Ver
SharedItinerary en app/models.py, donde esta el motivo entero.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Callable

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Alfabeto del codigo, sin los caracteres que se confunden al leerlos en voz
# alta o al copiarlos a mano: no hay 0 ni O, ni 1 ni I ni l. Un enlace de
# itinerario se dicta por telefono mas de lo que uno creeria.
ALFABETO = "23456789abcdefghjkmnpqrstuvwxyz"

# Largo del codigo. Con 31 caracteres posibles son 31^10, unos 49 bits: de
# sobra para que nadie llegue a un itinerario ajeno probando, y corto para que
# la URL se lea de un vistazo.
LARGO = 10

# Cuantas veces se reintenta si el codigo ya existe. Con 49 bits la colision es
# practicamente imposible, pero dos intentos cuestan nada y la alternativa es
# un error en la cara de alguien.
INTENTOS = 3


def nuevo_codigo() -> str:
    """Un codigo al azar, con el alfabeto que no se presta a confusion."""
    return "".join(secrets.choice(ALFABETO) for _ in range(LARGO))


def guardar(db: Session, construir: Callable[[str], dict]) -> str | None:
    """Guarda el itinerario y devuelve su codigo, o None si no se pudo.

    Recibe una funcion y no el payload ya armado porque el itinerario guardado
    lleva dentro su propio codigo: quien abre un enlace tiene que poder volver
    a compartirlo, y para eso la copia necesita saber como se llama. Como el
    codigo cambia en cada reintento, el payload se arma con el codigo de ese
    intento.

    **Nunca lanza.** Compartir es un añadido: si la base esta llena, lenta o
    caida, el itinerario tiene que llegar igual a quien lo pidio, solo que sin
    enlace. Un plan que falla entero porque no se pudo guardar una copia seria
    un mal negocio.
    """
    for _ in range(INTENTOS):
        codigo = nuevo_codigo()
        try:
            db.execute(
                text("""
                    INSERT INTO shared_itineraries (code, payload)
                    VALUES (:code, CAST(:payload AS jsonb))
                    ON CONFLICT (code) DO NOTHING
                """),
                {"code": codigo, "payload": _json(construir(codigo))},
            )
            db.commit()

            # ON CONFLICT DO NOTHING no dice si inserto, asi que se comprueba.
            # Va dentro del try junto con el INSERT: "nunca lanza" no se cumple
            # a medias, y un fallo al comprobar es tan capaz de tumbar el plan
            # como uno al insertar.
            existe = db.execute(
                text("SELECT 1 FROM shared_itineraries WHERE code = :code"),
                {"code": codigo},
            ).first()
        except Exception:
            db.rollback()
            logger.warning("no se pudo guardar el itinerario para compartir", exc_info=True)
            return None

        if existe:
            return codigo

    logger.warning("no se encontro un codigo libre en %s intentos", INTENTOS)
    return None


def leer(db: Session, codigo: str) -> dict | None:
    """El itinerario guardado, o None si el codigo no existe.

    Cuenta la apertura, que no es analitica: sirve para saber que se puede
    borrar sin molestar a nadie el dia que la tabla crezca. Si esa cuenta
    falla, el itinerario se devuelve igual.
    """
    fila = db.execute(
        text("SELECT payload FROM shared_itineraries WHERE code = :code"),
        {"code": codigo},
    ).first()
    if fila is None:
        return None

    try:
        db.execute(
            text("UPDATE shared_itineraries SET opened = opened + 1 WHERE code = :code"),
            {"code": codigo},
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("no se pudo contar la apertura de %s", codigo, exc_info=True)

    return fila[0]


def _json(payload: dict) -> str:
    import json

    return json.dumps(payload, default=str)
