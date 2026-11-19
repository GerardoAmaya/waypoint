"""Traza el contorno del Pacifico salvadoreño desde el catalogo.

    make costa

**La frontera sur del pais es el mar**, asi que el lugar mas austral de cada
franja de longitud esta practicamente en la playa. De cada vecindad se toma el
minimo, que quita los picos tierra adentro de las franjas donde el catalogo no
llega a la costa.

Existe porque la API marina **no sirve para decidir que es costa**: su rejilla
se engancha a la celda con agua mas cercana y le da 0.92 m de oleaje a
Concepcion de Ataco, que esta en la montaña a treinta kilometros. Lo que sale
de aqui se pega en `COSTA`, en services/mar.py.
"""

from __future__ import annotations

from sqlalchemy import text

from app.core.db import SessionLocal
from app.services.geo import haversine_km

# Menos lugares que esto en una franja y su minimo es una anecdota, no la
# costa: un solo hotel tierra adentro movia el contorno diez kilometros.
MINIMO_POR_FRANJA = 3

# Lugares conocidos con los que comprobar el corte, y de que lado caen.
CONTROL = {
    "El Cuco": (13.1667, -88.1167, True),
    "El Tunco": (13.4936, -89.3819, True),
    "El Zonte": (13.4936, -89.4400, True),
    "Costa del Sol": (13.3167, -88.9167, True),
    "La Libertad": (13.4883, -89.3222, True),
    "Santa Tecla": (13.6731, -89.2797, False),
    "San Salvador": (13.6929, -89.2182, False),
    "Ataco": (13.8697, -89.8467, False),
    "Santa Ana": (13.9942, -89.5597, False),
    "Suchitoto": (13.9356, -89.0272, False),
}


def main() -> int:
    db = SessionLocal()
    try:
        filas = db.execute(
            text("""
                SELECT round(st_x(geom::geometry)::numeric, 1) AS banda,
                       min(st_y(geom::geometry)) AS sur
                FROM places
                GROUP BY banda
                HAVING count(*) >= :minimo
                ORDER BY banda
            """),
            {"minimo": MINIMO_POR_FRANJA},
        ).fetchall()
    finally:
        db.close()

    crudo = [(float(f.banda), float(f.sur)) for f in filas]
    if len(crudo) < 5:
        print("el catalogo no da para trazar una costa")
        return 1

    costa = [
        (lon, min(lat for _, lat in crudo[max(0, i - 1) : i + 2]))
        for i, (lon, _) in enumerate(crudo)
    ]

    print("# Pegar en services/mar.py:\n")
    print("COSTA: tuple[tuple[float, float], ...] = (")
    for i in range(0, len(costa), 4):
        trozo = ", ".join(f"({lon}, {lat:.3f})" for lon, lat in costa[i : i + 4])
        print(f"    {trozo},")
    print(")")

    print(f"\n{'control':<18}{'km a la costa':>14}{'esperado':>11}{'':>3}")
    fallos = 0
    for nombre, (lat, lon, costero) in CONTROL.items():
        km = min(haversine_km(lat, lon, clat, clon) for clon, clat in costa)
        bien = (km <= 12.0) == costero
        fallos += not bien
        print(
            f"{nombre:<18}{km:>14.1f}{'costa' if costero else 'tierra':>11}"
            f"{'  ok' if bien else '  ✗'}"
        )
    if fallos:
        print(f"\n{fallos} control(es) del lado equivocado: revisá el corte")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
