"""Modelos ORM del catalogo de lugares."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from geoalchemy2 import Geography, Geometry
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Category(str, enum.Enum):
    """Categorias con las que se arma un itinerario.

    Deliberadamente pocas: son las decisiones que toma alguien planificando un
    dia, no la taxonomia completa de OpenStreetMap.
    """

    food = "food"
    nature = "nature"
    culture = "culture"
    viewpoint = "viewpoint"
    attraction = "attraction"
    lodging = "lodging"


class Place(Base):
    """Un lugar del catalogo.

    Cada parada de un itinerario sale de esta tabla, nunca del modelo. Esa es
    la garantia de que el sistema no puede inventar un restaurante.
    """

    __tablename__ = "places"
    __table_args__ = (
        # El par tipo+id identifica un objeto de OpenStreetMap de forma unica,
        # asi que recargar el catalogo actualiza en vez de duplicar.
        UniqueConstraint("osm_type", "osm_id", name="uq_places_osm"),
        # Indice espacial: sin el, cualquier consulta por radio recorre la
        # tabla entera.
        Index("ix_places_geom", "geom", postgresql_using="gist"),
        # Busqueda de nombres tolerante a las variaciones de OSM.
        Index(
            "ix_places_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
        Index("ix_places_category_active", "category", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    osm_type: Mapped[str] = mapped_column(String(8), nullable=False)
    # BigInteger es obligatorio: los identificadores de nodo de OSM pasaron
    # el limite de 32 bits hace mas de una decada. Con Integer, SQLAlchemy
    # convierte el parametro a INTEGER y Postgres rechaza el valor.
    osm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    name: Mapped[str] = mapped_column(String(300), nullable=False)
    category: Mapped[Category] = mapped_column(
        Enum(Category, name="place_category"), nullable=False
    )
    # Valor crudo de la etiqueta de OSM que determino la categoria. Sirve para
    # afinar el filtro despues sin volver a descargar todo.
    subcategory: Mapped[str | None] = mapped_column(String(64))

    geom: Mapped[object] = mapped_column(
        Geography(geometry_type="POINT", srid=4326), nullable=False
    )
    # Duplicadas a proposito: serializar a JSON sin convertir la geometria en
    # cada consulta es mas simple y el costo en espacio es despreciable.
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)

    # Etiquetas completas de OSM. Guardarlas evita volver a Overpass cuando se
    # necesite un dato que hoy no usamos.
    tags: Mapped[dict | None] = mapped_column(JSONB)

    quality_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Los descartados se guardan igual, marcados. Borrarlos impediria medir el
    # filtro y afinarlo despues.
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    rejected_reason: Mapped[str | None] = mapped_column(String(64))

    # Cuando dos registros de OSM son el mismo lugar, uno queda como canonico
    # y el otro apunta a el.
    duplicate_of: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class TravelEdge(Base):
    """Un traslado ya medido entre dos lugares del catalogo.

    Es la cache de OpenRouteService. La distancia entre dos puntos fijos no
    cambia, asi que se paga cupo una vez por par y no una vez por itinerario.

    **La clave incluye el sentido y el perfil, y las tres partes importan.** El
    sentido, porque las calles de un solo sentido y los retornos hacen que ir
    no cueste lo mismo que volver; asumir simetria para ahorrar la mitad de las
    filas mete un error que despues nadie encuentra. El perfil, porque a pie y
    en carro son redes distintas: un sendero que el peaton cruza no existe para
    el carro.
    """

    __tablename__ = "travel_edges"
    __table_args__ = (
        Index("ix_travel_edges_origin", "origin_id"),
        Index("ix_travel_edges_profile", "profile"),
    )

    origin_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("places.id", ondelete="CASCADE"), primary_key=True
    )
    destination_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("places.id", ondelete="CASCADE"), primary_key=True
    )
    # "driving-car" o "foot-walking", tal como los nombra OpenRouteService.
    profile: Mapped[str] = mapped_column(String(24), primary_key=True)

    distance_km: Mapped[float] = mapped_column(Float, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)

    # "ors" o "estimated". Solo se guardan las de ORS: cachear una estimacion
    # seria enterrar para siempre un valor que la proxima vez podria ser real.
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="ors", default="ors"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PlaceName(Base):
    """Un nombre de lugar: departamento, municipio, distrito, pueblo o barrio.

    **No es un punto de interes y por eso no vive en `places`.** Confundirlos
    causaba un fallo real: "vivo en Mejicanos" no resolvia nada, porque lo
    unico llamado Mejicanos en el catalogo son cuatro puestos de comida y el
    motor —con razon— se niega a anclar un viaje en un cafe. Mejicanos no es un
    destino, es un lugar donde la gente vive.

    Tener tabla propia tambien mantiene separadas las dos busquedas por nombre.
    Con tres mil nombres de barrio dentro de `places`, la busqueda difusa
    tendria tres mil candidatos mas donde equivocarse, y ya se equivoca sin
    ayuda: "Hotel Barcelo" devuelve "Hotel La Parcela".
    """

    __tablename__ = "place_names"
    __table_args__ = (
        UniqueConstraint("osm_type", "osm_id", name="uq_place_names_osm"),
        Index("ix_place_names_geom", "geom", postgresql_using="gist"),
        Index(
            "ix_place_names_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
        Index("ix_place_names_kind_active", "kind", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    osm_type: Mapped[str] = mapped_column(String(16), nullable=False)
    osm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # "admin4" (departamento), "admin6" (municipio), "admin8" (distrito),
    # "city", "town", "village", "suburb", "neighbourhood".
    kind: Mapped[str] = mapped_column(String(16), nullable=False)

    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    geom: Mapped[object] = mapped_column(
        Geography(geometry_type="POINT", srid=4326), nullable=False
    )

    # Del recuadro del limite administrativo cuando OSM lo trae, y de un valor
    # por tipo cuando el lugar es solo un punto: un departamento y un barrio no
    # pueden buscar en el mismo radio. Medido sobre los limites de El Salvador,
    # la mediana da 37.8 km para un departamento y 7.3 km para un municipio.
    radius_m: Mapped[int] = mapped_column(Integer, nullable=False)

    # Destinos del catalogo dentro del radio. Es el dato que decide si el
    # nombre sirve para armar un dia, y se guarda medido para poder afinar el
    # umbral sin volver a consultar Overpass.
    destinations_nearby: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    # Los pobres se guardan marcados, no se borran: igual que en `places`,
    # borrarlos impediria medir el filtro.
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    rejected_reason: Mapped[str | None] = mapped_column(String(32))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class RouteLeg(Base):
    """El trazo por carretera de un tramo, para dibujarlo en el mapa.

    **Tabla propia y no una columna de `travel_edges`, aunque comparta clave.**
    La primera version la puso ahi razonando que la distancia y el trazo tienen
    el mismo ciclo de vida. No lo tienen, y se vio corriendo: OpenRouteService
    mide el cupo por endpoint, asi que la matriz puede estar agotada mientras
    direcciones sigue contestando. Un itinerario queda entonces con distancias
    estimadas —sin arista guardada, porque solo se guardan las medidas— y trazo
    real a la vez.

    Como columna de `travel_edges` eso no se podia guardar: el UPDATE no
    encontraba fila, el trazo se tiraba, y la peticion siguiente lo volvia a
    pedir. Se gastaba cupo en cada consulta para descartar el resultado.

    La distancia no se guarda aca: la mide la matriz y vive en `travel_edges`.
    Duplicarla dejaria dos numeros que pueden discrepar.
    """

    __tablename__ = "route_legs"
    __table_args__ = (Index("ix_route_legs_origin", "origin_id"),)

    origin_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("places.id", ondelete="CASCADE"), primary_key=True
    )
    destination_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("places.id", ondelete="CASCADE"), primary_key=True
    )
    # "driving-car" o "foot-walking", igual que en travel_edges: a pie y en
    # carro son redes distintas y el trazo tampoco es el mismo.
    profile: Mapped[str] = mapped_column(String(24), primary_key=True)

    geometry: Mapped[object] = mapped_column(
        Geometry(geometry_type="LINESTRING", srid=4326, spatial_index=False),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
