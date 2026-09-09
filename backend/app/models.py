"""Modelos ORM del catalogo de lugares."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from geoalchemy2 import Geography
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
