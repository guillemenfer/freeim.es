# Detector de cuotas con valor - Codere vs Sofascore

Compara las cuotas 1X2 de fútbol publicadas en la portada de Codere con una
probabilidad estimada a partir del historial de goles reciente de cada
equipo (datos de Sofascore), usando un modelo de Poisson. Cuando la cuota de
Codere implica una probabilidad bastante menor que la del modelo, lo marca
como "cuota con valor" y avisa por email.

## Aviso importante

- Este programa usa las **APIs internas no oficiales** de Codere y Sofascore
  (las mismas que usan sus propias webs). No son APIs públicas documentadas:
  pueden cambiar o dejar de funcionar sin aviso, y su uso automatizado puede
  no estar contemplado en los términos de uso de esos sitios. Es un proyecto
  para uso personal/educativo; usalo bajo tu propio criterio y
  responsabilidad.
- El modelo estadístico es deliberadamente simple (Poisson con promedio de
  goles de los últimos partidos). **No es asesoramiento de apuestas ni
  garantiza ganancias.** Una "cuota con valor" es solo una discrepancia
  frente al modelo, no un error real de la casa.
- Apostar dinero implica riesgo económico y de ludopatía. Si jugás, hacelo
  con límites y de forma responsable.

## Instalación

```bash
pip install -r requirements.txt
```

Copiá `.env.example` a `.env` y completá tus datos:

```bash
cp .env.example .env
```

### Configurar el email (Gmail)

1. Activá la verificación en 2 pasos en tu cuenta de Google (si no la tenés
   activada, `myaccount.google.com/apppasswords` no va a estar disponible).
2. Andá a https://myaccount.google.com/apppasswords y generá una
   "contraseña de aplicación" (16 caracteres, sin espacios al pegarla).
3. En `.env`, poné `SMTP_USER` con tu Gmail y `SMTP_PASSWORD` con esa
   contraseña de aplicación (no la contraseña normal de tu cuenta).
4. `EMAIL_TO` es el destinatario de las alertas (podés dejarlo igual a
   `SMTP_USER` para recibirlas vos mismo).

## Uso

```bash
# Corrida única, muestra resultados en consola y envía email si hay valor
python main.py

# Corrida única sin enviar email (solo para probar)
python main.py --dry-run

# Bucle continuo, revisa cada CHECK_INTERVAL_MINUTES minutos (Ctrl+C para salir)
python main.py --loop
```

Para que corra solo periódicamente sin dejar una consola abierta, podés
programarlo con el Programador de tareas de Windows ejecutando
`python main.py --dry-run` (o sin `--dry-run`) cada X minutos, en vez de
usar `--loop`.

## Cómo funciona

1. `codere_client.py` trae los partidos de fútbol destacados de Codere con
   mercado 1X2 (equipos, liga, fecha, cuotas).
2. `sofascore_client.py` busca cada equipo por nombre en Sofascore y calcula
   el promedio de goles marcados/recibidos como local y como visitante en
   sus últimos partidos (`FORM_MATCHES`).
3. `probability.py` combina esos promedios en goles esperados (xG simple) y
   calcula P(1)/P(X)/P(2) con una distribución de Poisson. También le quita
   el margen de la casa a las cuotas de Codere para obtener su probabilidad
   implícita real.
4. `value_finder.py` compara probabilidad del modelo vs. probabilidad
   implícita; si la diferencia supera `EDGE_THRESHOLD` (5 puntos por
   defecto), lo marca como cuota con valor.
5. `notifier.py` envía un email con el resumen si se encontró algo.

## Ajustes útiles en `.env`

- `EDGE_THRESHOLD`: subilo si recibís demasiadas alertas poco confiables,
  bajalo si querés más sensibilidad.
- `FORM_MATCHES`: más partidos = promedio más estable pero menos sensible a
  la forma reciente.
- `CODERE_HIGHLIGHTS_COUNT`: cuántos partidos destacados pedir a Codere.

## Limitaciones conocidas

- Solo cubre partidos que Codere muestra como "destacados" en portada (no
  todo el catálogo de ligas).
- El emparejamiento de equipos entre Codere y Sofascore es por similitud de
  nombre; en casos raros puede fallar (se descarta el partido si la
  similitud es baja, ver `NAME_MATCH_THRESHOLD`).
- No usa lesiones, alineaciones, clima ni otros factores: solo goles
  históricos.
