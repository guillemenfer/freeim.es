# Detector de cuotas con valor - Liga Profesional Argentina, Eliteserien y Allsvenskan

Compara las cuotas de fútbol de las ligas configuradas (por defecto: Liga
Profesional Argentina, Eliteserien de Noruega y Allsvenskan de Suecia)
publicadas por Codere (mercados 1X2, Total de Goles, Ambos Marcan y Total de
Córners) con una probabilidad estimada a partir del historial reciente de
cada equipo (datos de ESPN), usando un modelo de Poisson calibrado por
separado para cada liga. Solo muestra selecciones que cumplen **las dos
condiciones a la vez**:

- **Valor**: la cuota de Codere implica menos probabilidad de la que estima
  el modelo (edge entre `EDGE_THRESHOLD` y `MAX_TRUSTED_EDGE`).
- **Alta probabilidad**: el modelo le da al menos `HIGH_PROB_THRESHOLD`
  (70% por defecto) de probabilidad de ocurrir.

## Cómo se usa hoy

Corre solo cada 30 minutos en **GitHub Actions** (`.github/workflows/detect.yml`)
y publica los resultados como `docs/data.json`, servido por **GitHub Pages** en:

**https://guillemenfer.github.io/freeim.es/**

Esa página web es "la app": no hace falta instalar nada ni dejar la PC
prendida, se actualiza sola. El modo por email (`notifier.py`) sigue
disponible en el código para uso local manual, pero no se dispara solo.

## Aviso importante

- Este programa usa la **API interna no oficial** de Codere (la misma que usa
  su web) y la **API pública no documentada** de ESPN. Ninguna es una API
  oficial con contrato estable: pueden cambiar o dejar de funcionar sin
  aviso. Es un proyecto para uso personal/educativo; usalo bajo tu propio
  criterio y responsabilidad.
  - (Nota: originalmente se usaba Sofascore para las estadísticas, pero
    empezó a bloquear con 403 las peticiones hechas desde las IPs de
    datacenter de GitHub Actions. Se migró a ESPN, que no tuvo ese problema.)
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

1. `codere_client.py` trae el fixture completo de las ligas configuradas en
   `CODERE_LEAGUE_NODE_IDS` con 4 mercados: 1X2, Total de Goles, Ambos Marcan
   y Total de Córners.
2. `espn_client.py` busca cada equipo por nombre en ESPN y calcula
   el promedio de goles y córners a favor/en contra como local y como
   visitante en sus últimos partidos (`FORM_MATCHES`), excluyendo amistosos.
3. `probability.py` combina esos promedios (suavizados hacia un promedio
   general, ver `SHRINKAGE_K`) en goles/córners esperados y calcula, con una
   distribución de Poisson: P(1)/P(X)/P(2), P(over/under goles), P(ambos
   marcan) y P(over/under córners). También le quita el margen de la casa a
   las cuotas de Codere para obtener su probabilidad implícita real.
4. `value_finder.py` compara, mercado por mercado, probabilidad del modelo
   vs. probabilidad implícita; si la diferencia está entre `EDGE_THRESHOLD`
   y `MAX_TRUSTED_EDGE`, lo marca como cuota con valor (los edges por encima
   de `MAX_TRUSTED_EDGE` se descartan por ser casi siempre error de modelo).
5. `notifier.py` envía un email con el resumen si se lo llama manualmente
   (no se usa en la corrida automática de GitHub Actions, que en cambio
   publica `docs/data.json` para la web).

## Ajustes útiles en `.env`

- `CODERE_LEAGUE_NODE_IDS`: ligas de Codere a seguir (`nodeId:Nombre`,
  separadas por coma). Para agregar otra liga, hay que ubicar su NodeId: en
  la web de Codere, entrar a Fútbol → el país → la liga, y mirar en las
  herramientas de desarrollador la llamada a
  `NavigationService/Event/GetEvents?parentId=<NodeId>`.
- `ESPN_LEAGUE_SLUGS`: mapea cada nombre de liga (el mismo `Nombre` usado en
  `CODERE_LEAGUE_NODE_IDS`) a su slug en ESPN. **Toda liga que agregues a
  `CODERE_LEAGUE_NODE_IDS` necesita también su entrada acá**, si no, se
  ignora esa liga (queda un aviso en el log). El slug se puede ubicar
  navegando espn.com/soccer/ y mirando la URL de la liga.
- `EDGE_THRESHOLD`: subilo si recibís demasiadas alertas poco confiables,
  bajalo si querés más sensibilidad.
- `MAX_TRUSTED_EDGE`: edges por encima de esto se descartan directamente
  (casi siempre son error de modelo en cruces de nivel muy distinto, no una
  cuota real mal puesta).
- `FORM_MATCHES`: más partidos = promedio más estable pero menos sensible a
  la forma reciente.

## Limitaciones conocidas

- El emparejamiento de equipos entre Codere y ESPN es por similitud de
  nombre; en casos raros puede fallar (se descarta el partido si la
  similitud es baja, ver `NAME_MATCH_THRESHOLD`).
- El mercado de córners necesita las estadísticas de cada partido reciente
  (una petición extra por partido a ESPN); si ESPN no tiene esos
  datos cargados para algún equipo, ese mercado se omite para ese partido.
- No usa lesiones, alineaciones, clima ni otros factores: solo estadísticas
  históricas de goles/córners.
