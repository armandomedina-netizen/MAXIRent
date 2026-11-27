#!/usr/bin/env bash
# Espera a que el servidor de Maxinet acepte conexiones antes de correr una automatización (ADR 0034).
#
# Maxinet es un servidor externo y único del que dependen todos los workflows: cuando se cae (rechaza conexiones,
# 22-nov-2026) fallan todos a la vez y los diarios quedan sin datos hasta el día siguiente. Esta sonda reintenta
# cada pocos segundos hasta que responde o se acaba la espera; si se acaba, el workflow falla como antes.
#
# Variables de entorno:
#   BASE_URL       URL base de Maxinet (secret MAXINET_BASE_URL). Nunca se imprime.
#   MINUTOS        espera máxima en minutos (por defecto 60)
#   ESPERA_MAX_SEG espera máxima en segundos; tiene prioridad sobre MINUTOS (pruebas). El reloj es de segundos enteros:
#                  la espera real puede quedar hasta 1 s por debajo del máximo.
#   SONDEO_SEG     segundos entre intentos (por defecto 30)
#   AVISO_CADA     cada cuántos intentos fallidos repite el aviso (por defecto 10)
#
# "Arriba" = cualquier respuesta HTTP 200 a 499: el servidor atiende. Sin conexión (curl 7: rechazada; 28: tiempo agotado;
# 6: DNS) o con HTTP 5xx (el servidor responde pero la aplicación está caída) cuenta como caído.
set -u

base="${BASE_URL:-}"
if [ -z "$base" ]; then
  echo "::error::Falta la URL de Maxinet (secret MAXINET_BASE_URL)"
  exit 1
fi
base="${base%/}"
maximo="${ESPERA_MAX_SEG:-$(( ${MINUTOS:-60} * 60 ))}"
sondeo="${SONDEO_SEG:-30}"
aviso_cada="${AVISO_CADA:-10}"

inicio="$(date +%s)"
intento=0
while true; do
  intento=$((intento + 1))
  rc=0
  codigo="$(curl -sS -o /dev/null -w '%{http_code}' --connect-timeout 10 --max-time 30 "$base/" 2>/dev/null)" || rc=$?
  codigo="${codigo:-000}"
  if [ "$rc" -eq 0 ] && [ "$codigo" -ge 200 ] && [ "$codigo" -lt 500 ]; then
    espera=$(( $(date +%s) - inicio ))
    if [ "$intento" -gt 1 ]; then
      echo "::warning::Maxinet volvió a responder tras esperar $((espera / 60)) min $((espera % 60)) s ($intento intentos)"
    else
      echo "Maxinet responde (HTTP $codigo)"
    fi
    exit 0
  fi
  espera=$(( $(date +%s) - inicio ))
  if [ "$intento" -eq 1 ] || [ $(( (intento - 1) % aviso_cada )) -eq 0 ]; then
    echo "Maxinet no responde (curl $rc, HTTP $codigo): lleva $((espera / 60)) min esperando, máximo $((maximo / 60)) min"
  fi
  if [ "$espera" -ge "$maximo" ]; then
    echo "::error::Maxinet no respondió en $((maximo / 60)) min (último intento: curl $rc, HTTP $codigo); no se ejecutó la automatización"
    exit 1
  fi
  sleep "$sondeo"
done
