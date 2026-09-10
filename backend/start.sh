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

# **Las migraciones corren aca y no en el preDeployCommand de Railway.**
#
# La primera version confiaba en ese comando. No corrio: el despliegue salio
# con PostGIS instalado, cero tablas, y un /health diciendo "ok". El fallo
# aparecio mucho despues, al intentar cargar los datos.
#
# Hay dos explicaciones posibles y desde fuera no se distinguen. La clave
# espera un arreglo y estaba escrita como cadena; y Railway deprecó Config as
# Code, con los servicios nuevos sin poder optar por el. Como no se puede
# saber cual fue, no se apuesta a ninguna.
#
# Migrar al arrancar tiene una pega conocida: con varias replicas, todas
# correrian Alembic a la vez. No aplica aca, porque el limite por IP obliga a
# una sola instancia con un solo worker por la razon de mas arriba. Se elige
# lo verificable —esto se prueba con un docker run— sobre lo teoricamente
# mejor que no se puede comprobar.
#
# Si falla, el contenedor no arranca y el despliegue se cae ruidosamente. Es
# lo que se quiere: peor que fallar es servir a medio migrar.
echo "==> Aplicando migraciones"
alembic upgrade head

exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "$PUERTO" \
  --workers 1 \
  --proxy-headers \
  --forwarded-allow-ips '*'
