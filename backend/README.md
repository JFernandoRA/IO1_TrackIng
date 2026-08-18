# TrackIng API — Sistema Inteligente de Rutas Académicas Curriculares

Backend en FastAPI para la planificación académica de estudiantes de ingeniería de la USAC.

## Estructura

```
api/
├── main.py                    # App FastAPI, CORS, manejo global de errores
├── config.py                  # Carga y cachea las mallas reales + el JSON de ejemplo
├── models/                    # Modelos Pydantic (malla, requests, responses)
├── services/                  # Lógica de negocio (grafos, ruta, horario, validación)
├── routers/                   # Endpoints agrupados por dominio
├── data/malla_curricular.json # Datos de ejemplo (12 cursos, carrera "sistemas", CON horarios)
└── data/mallas/                # Mallas reales, una por carrera/pénsum (SIN horarios)
requirements.txt
vercel.json
```

## Correr localmente

```bash
pip install -r requirements.txt
cd api
uvicorn main:app --reload
```

Luego abre http://127.0.0.1:8000/docs para la documentación interactiva (Swagger UI).

## Desplegar en Vercel

```bash
npm i -g vercel
vercel
```

`vercel.json` ya está configurado para construir `api/main.py` con `@vercel/python`
y enrutar todo `/api/*` hacia esa función serverless.

## Endpoints

| Método | Ruta                        | Descripción |
|--------|-----------------------------|-------------|
| GET    | `/api/carreras`             | Lista las carreras/pénsums disponibles (usa `carrera_id` o nombre en los demás endpoints) |
| GET    | `/api/malla`                | Malla curricular completa, filtrable por `?carrera=` |
| POST   | `/api/calcular-ruta`        | Ruta académica óptima según cursos aprobados y meta |
| GET    | `/api/validar-prerequisitos`| Verifica si se puede inscribir un curso dado lo aprobado (requiere `?carrera=`) |
| POST   | `/api/generar-horario`      | Horario semanal sin conflictos para una lista de cursos (usa el JSON de ejemplo, ver abajo) |
| GET    | `/api/health`                | Health check |

## Datos

Hay dos fuentes de datos con propósitos distintos:

- **`api/data/mallas/*.json`** — las 11 mallas curriculares reales (una por
  carrera; Ciencias y Sistemas tiene dos pénsums, 2022 y 2025). Alimentan
  `/api/malla`, `/api/carreras`, `/api/calcular-ruta` y `/api/validar-prerequisitos`.
  Cada archivo trae `codigo`, `nombre`, `creditos`, `semestre`, `prerequisitos`
  y `obligatorio` (booleano) por curso. **No incluyen horarios** (profesor/
  día/hora/aula), así que esos cursos no tienen secciones que ofrecer a
  `/api/generar-horario`.

  Importante: el mismo código de curso puede tener `semestre` y/o
  `prerequisitos` distintos según la carrera (son cursos de área común
  ubicados en puntos diferentes de cada pénsum), por eso la malla se
  mantiene separada por carrera y **no** se fusiona en un solo diccionario
  global. `config.resolver_carrera()` acepta el `carrera_id` (ej.
  `ingenieriaCivil`), el nombre completo (ej. `Ingeniería Civil`, sin
  distinguir mayúsculas/acentos) o la llave exacta con año (ej.
  `ingenieriaEnCienciasYSistemas_2025`); si hay más de un pénsum para la
  misma carrera y no se especifica el año, se usa el más reciente.

  El campo `obligatorio` se expone tal cual viene en la fuente (`true`/
  `false`); todavía no hay una categorización más fina (electivo/optativo).

- **`api/data/malla_curricular.json`** — el JSON de ejemplo original (12
  cursos, carrera "sistemas"), el único que trae `horarios_disponibles`.
  Sigue siendo la fuente de `/api/generar-horario` porque las mallas reales
  no tienen datos de horario que ofrecer.

## Notas de implementación

- **Ruta óptima (Fase 1):** heurística basada en orden topológico de
  `networkx` sobre el grafo de prerequisitos, repartiendo cursos en
  semestres respetando `carga_maxima_por_semestre` y priorizando según
  `meta.tipo` (`adelantar`, `nivelar`, `graduacion_rapida`, `personalizada`).
  Ver `services/ruta_service.py`. El router resuelve primero la carrera
  con `config.resolver_carrera()` y pasa al servicio solo la malla de esa
  carrera; el servicio ya no filtra por carrera internamente.
- **`postrequisitos`:** no viene en los datos fuente; `config.cargar_carreras()`
  lo calcula invirtiendo `prerequisitos` dentro de cada carrera al cargar.
- **Fase 2 (MIP):** el `requirements.txt` incluye `pulp` para una futura
  formulación de programación entera que minimice el número de semestres;
  no está implementada aún — el endpoint actual usa siempre la heurística.
- **Horario sin conflictos:** heurística *greedy* que ordena los cursos
  por número de secciones disponibles (más restringidos primero) y evita
  solapes de día/hora, respetando preferencia de franja horaria y días libres.
  Ver `services/horario_service.py`. Solo tiene datos con los que trabajar
  en el JSON de ejemplo (ver sección Datos).
- **Sin base de datos:** todo se sirve desde JSON estático, cacheado en
  memoria con `lru_cache` para minimizar cold starts en Vercel.
