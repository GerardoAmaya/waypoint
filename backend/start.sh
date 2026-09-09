#!/bin/sh
# Arranque en produccion.
#
# **Un solo worker, a proposito.** El limite por IP lleva su cuenta en memoria
# del proceso, asi que con cuatro workers cada uno tendria la suya y el techo
# real seria cuatro veces el configurado. La decision de no meter Redis obliga a
# un solo proceso, y eso se fija aca en vez de dejarlo al azar del entorno.
#
# Si algun dia hace falta escalar, el orden es: mover la cuenta a un almacen
# compartido primero, subir los workers despues. Al reves, el limite deja de
# limitar sin que nada falle ni avise.
set -e

# Railway y Fly inyectan el puerto por variable. La forma exec de CMD no expande
# variables, por eso el arranque pasa por este guion.
PUERTO="${PORT:-8000}"

exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "$PUERTO" \
  --workers 1 \
  --proxy-headers \
  --forwarded-allow-ips '*'
