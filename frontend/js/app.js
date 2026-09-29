const MODOS = [
  { valor: "avanzar", titulo: "Adelantarme", descripcion: "Cerrar la carrera antes de tiempo, usando el máximo de créditos que me permite mi promedio." },
  { valor: "nivelarse", titulo: "Nivelarme", descripcion: "Ponerme al día lo más rápido posible sin atrasarme más." },
  { valor: "tiempo_normal", titulo: "Tiempo normal", descripcion: "No sobrecargarme: solo llevar la carga oficial del pénsum para mi semestre." },
];

const state = {
  carreras: [],
  archivo: null,
  malla: null,
  cursos: [],
  semestreActual: null,
  marcados: new Set(),
  noSemestre: new Set(),
  noVacaciones: new Set(),
  descartados: new Set(),
  modoMarcado: "ganados",
  iniciarEnVacaciones: false,
  modo: "nivelarse",
  ultimoPlan: null,
};

const TIPOS_ETIQUETA = {
  social_humanistica: "Social Humanística",
  idioma: "Idioma técnico",
  optativo: "Optativo",
};

const pantallaCarreras = document.getElementById("pantalla-carreras");
const pantallaFormulario = document.getElementById("pantalla-formulario");
const pantallaResultado = document.getElementById("pantalla-resultado");

const listaCarreras = document.getElementById("lista-carreras");
const tituloFormulario = document.getElementById("titulo-formulario");
const selectSemestre = document.getElementById("select-semestre");
const gridCursos = document.getElementById("grid-cursos");
const inputPromedio = document.getElementById("input-promedio");
const opcionesModo = document.getElementById("opciones-modo");
const btnCalcular = document.getElementById("btn-calcular");
const campoIdiomas = document.getElementById("campo-idiomas");
const checkIdiomas = document.getElementById("check-idiomas");
const mensajeError = document.getElementById("mensaje-error");

const btnVolverCarreras = document.getElementById("btn-volver-carreras");
const btnVolverFormulario = document.getElementById("btn-volver-formulario");
const resumenPlan = document.getElementById("resumen-plan");
const gridResultado = document.getElementById("grid-resultado");
const btnLimpiar = document.getElementById("btn-limpiar");
const btnLimpiarResultado = document.getElementById("btn-limpiar-resultado");
const btnDescargarPdf = document.getElementById("btn-descargar-pdf");

function mostrarPantalla(pantalla) {
  [pantallaCarreras, pantallaFormulario, pantallaResultado].forEach(p => p.classList.add("oculto"));
  pantalla.classList.remove("oculto");
}

async function cargarCarreras() {
  const respuesta = await fetch("/api/carreras");
  state.carreras = await respuesta.json();
  renderizarListaCarreras();
}

function renderizarListaCarreras() {
  listaCarreras.innerHTML = "";
  state.carreras.forEach(carrera => {
    const tarjeta = document.createElement("div");
    tarjeta.className = "tarjeta-carrera";

    const titulo = document.createElement("h3");
    titulo.textContent = carrera.nombre;

    const detalle = document.createElement("p");
    detalle.textContent = `${carrera.pensum} ${carrera.vigente_desde} · ${carrera.total_cursos} cursos`;

    tarjeta.appendChild(titulo);
    tarjeta.appendChild(detalle);
    tarjeta.addEventListener("click", () => seleccionarCarrera(carrera));

    listaCarreras.appendChild(tarjeta);
  });
}

async function seleccionarCarrera(carrera) {
  state.archivo = carrera.archivo;
  const respuesta = await fetch(`/api/malla/${carrera.archivo}`);
  state.malla = await respuesta.json();
  state.cursos = state.malla.cursos;
  state.dependientesDirectos = construirDependientesDirectos(state.cursos);
  state.cursosPorCodigo = new Map(state.cursos.map(c => [c.codigo, c]));
  state.noSemestre = new Set();
  state.noVacaciones = new Set();
  state.descartados = new Set();
  state.modoMarcado = "ganados";
  document.querySelector('input[name="modo-marcado"][value="ganados"]').checked = true;
  checkIdiomas.checked = false;
  campoIdiomas.classList.toggle("oculto", !state.cursos.some(c => /idioma t[eé]cnico/i.test(c.nombre)));

  tituloFormulario.textContent = `${state.malla.carrera} · ${state.malla.pensum} ${state.malla.vigente_desde}`;
  construirSelectSemestre();
  renderizarOpcionesModo();
  mensajeError.classList.add("oculto");

  mostrarPantalla(pantallaFormulario);
}

function construirSelectSemestre() {
  const semestres = [...new Set(state.cursos.map(c => c.semestre).filter(s => s != null))].sort((a, b) => a - b);
  selectSemestre.innerHTML = "";
  semestres.forEach(numero => {
    const opcion = document.createElement("option");
    opcion.value = `s-${numero}`;
    opcion.textContent = `Semestre ${numero}`;
    selectSemestre.appendChild(opcion);

    const vacaciones = document.createElement("option");
    vacaciones.value = `v-${numero}`;
    vacaciones.textContent = `Vacaciones de semestre ${numero}`;
    selectSemestre.appendChild(vacaciones);
  });
  selectSemestre.value = `s-${semestres[0]}`;
  aplicarSeleccionPeriodo();
}
function aplicarSeleccionPeriodo() {
  const [tipo, numero] = selectSemestre.value.split("-");
  state.iniciarEnVacaciones = tipo === "v";
  state.semestreActual = Number(numero) + (state.iniciarEnVacaciones ? 1 : 0);
  recalcularMarcadosPorDefecto();
  state.marcados.forEach(codigo => {
    state.noSemestre.delete(codigo);
    state.noVacaciones.delete(codigo);
    state.descartados.delete(codigo);
  });
  renderizarGridCursos();
}

selectSemestre.addEventListener("change", aplicarSeleccionPeriodo);

document.querySelectorAll('input[name="modo-marcado"]').forEach(radio => {
  radio.addEventListener("change", () => {
    state.modoMarcado = radio.value;
  });
});

function recalcularMarcadosPorDefecto() {
  state.marcados = new Set(
    state.cursos
      .filter(c => (c.obligatorio ?? true) && c.semestre < state.semestreActual)
      .map(c => c.codigo)
  );
}

function construirDependientesDirectos(cursos) {
  const mapa = new Map();
  cursos.forEach(curso => {
    (curso.prerequisitos || []).forEach(prereq => {
      if (!mapa.has(prereq)) mapa.set(prereq, []);
      mapa.get(prereq).push(curso.codigo);
    });
  });
  return mapa;
}

function obtenerDependientesTransitivos(codigo) {
  const visitados = new Set();
  const pila = [...(state.dependientesDirectos.get(codigo) || [])];
  while (pila.length > 0) {
    const actual = pila.pop();
    if (visitados.has(actual)) continue;
    visitados.add(actual);
    (state.dependientesDirectos.get(actual) || []).forEach(dep => pila.push(dep));
  }
  return visitados;
}

function obtenerPrerequisitosTransitivos(codigo) {
  const visitados = new Set();
  const curso = state.cursosPorCodigo.get(codigo);
  const pila = [...(curso?.prerequisitos || [])];
  while (pila.length > 0) {
    const actual = pila.pop();
    if (visitados.has(actual)) continue;
    visitados.add(actual);
    const cursoActual = state.cursosPorCodigo.get(actual);
    (cursoActual?.prerequisitos || []).forEach(prereq => pila.push(prereq));
  }
  return visitados;
}

function renderizarGridCursos() {
  gridCursos.innerHTML = "";
  const semestres = [...new Set(state.cursos.map(c => c.semestre).filter(s => s != null))].sort((a, b) => a - b);

  const excluidosArrastrados = new Set();
  state.cursos.forEach(c => {
    if (estaDescartado(c.codigo)) {
      obtenerDependientesTransitivos(c.codigo).forEach(dep => excluidosArrastrados.add(dep));
    }
  });

  semestres.forEach(numero => {
    const columna = document.createElement("div");
    columna.className = "columna-semestre";

    const titulo = document.createElement("h4");
    titulo.textContent = `Semestre ${numero}`;
    columna.appendChild(titulo);

    state.cursos
      .filter(c => c.semestre === numero)
      .forEach(curso => {
        const bloque = document.createElement("div");
        const esOptativo = !(curso.obligatorio ?? true);
        const marcado = state.marcados.has(curso.codigo);
        const excluido = estaDescartado(curso.codigo);
        const excluidoPorArrastre = !excluido && !marcado && excluidosArrastrados.has(curso.codigo);
        let claseEstado = marcado ? "curso-marcado" : "curso-pendiente";
        if (excluido) claseEstado = "curso-excluido";
        else if (excluidoPorArrastre) claseEstado = "curso-excluido-arrastre";
        bloque.className = `curso ${claseEstado}${esOptativo ? " curso-optativo" : ""}`;

        const codigo = document.createElement("span");
        codigo.className = "curso-codigo";
        codigo.textContent = `${curso.codigo} · ${curso.creditos ?? 0} créd.`;
        if (!esOptativo) codigo.prepend(crearPuntoObligatorio());

        const nombre = document.createElement("span");
        nombre.textContent = curso.nombre;

        bloque.appendChild(codigo);
        bloque.appendChild(nombre);

        if (!excluido && !marcado && (state.noSemestre.has(curso.codigo) || state.noVacaciones.has(curso.codigo))) {
          const restriccion = document.createElement("span");
          restriccion.className = "etiqueta-restriccion";
          restriccion.textContent = state.noSemestre.has(curso.codigo) ? "solo vacaciones" : "solo semestre";
          bloque.appendChild(restriccion);
        }
        bloque.addEventListener("click", () => alternarMarcado(curso.codigo));

        columna.appendChild(bloque);
      });

    gridCursos.appendChild(columna);
  });
}

function estaDescartado(codigo) {
  return state.descartados.has(codigo)
    || (state.noSemestre.has(codigo) && state.noVacaciones.has(codigo));
}

function crearPuntoObligatorio() {
  const punto = document.createElement("span");
  punto.className = "punto-obligatorio";
  punto.title = "Curso obligatorio";
  punto.textContent = "● ";
  return punto;
}

function alternarDescartado(codigo) {
  if (state.marcados.has(codigo)) return;
  if (estaDescartado(codigo)) {
    state.descartados.delete(codigo);
    state.noSemestre.delete(codigo);
    state.noVacaciones.delete(codigo);
  } else {
    state.descartados.add(codigo);
    state.noSemestre.delete(codigo);
    state.noVacaciones.delete(codigo);
  }
  renderizarGridCursos();
}

function alternarRestriccion(codigo, conjunto) {
  if (state.marcados.has(codigo)) return; 
  state.descartados.delete(codigo);
  if (conjunto.has(codigo)) conjunto.delete(codigo);
  else conjunto.add(codigo);
  renderizarGridCursos();
}

function alternarMarcado(codigo) {
  if (state.modoMarcado === "descartar") {
    alternarDescartado(codigo);
    return;
  }
  if (state.modoMarcado === "no-semestre") {
    alternarRestriccion(codigo, state.noSemestre);
    return;
  }
  if (state.modoMarcado === "no-vacaciones") {
    alternarRestriccion(codigo, state.noVacaciones);
    return;
  }
  if (state.marcados.has(codigo)) {
    state.marcados.delete(codigo);
    obtenerDependientesTransitivos(codigo).forEach(dep => state.marcados.delete(dep));
  } else {
    state.marcados.add(codigo);
    obtenerPrerequisitosTransitivos(codigo).forEach(prereq => state.marcados.add(prereq));
    state.marcados.forEach(marcado => {
      state.noSemestre.delete(marcado);
      state.noVacaciones.delete(marcado);
      state.descartados.delete(marcado);
    });
  }
  renderizarGridCursos();
}

function renderizarOpcionesModo() {
  opcionesModo.innerHTML = "";
  MODOS.forEach(modo => {
    const opcion = document.createElement("div");
    opcion.className = `opcion-modo${state.modo === modo.valor ? " seleccionada" : ""}`;

    const titulo = document.createElement("h4");
    titulo.textContent = modo.titulo;

    const descripcion = document.createElement("p");
    descripcion.textContent = modo.descripcion;

    opcion.appendChild(titulo);
    opcion.appendChild(descripcion);
    opcion.addEventListener("click", () => {
      state.modo = modo.valor;
      renderizarOpcionesModo();
    });

    opcionesModo.appendChild(opcion);
  });
}

async function calcularRuta() {
  mensajeError.classList.add("oculto");

  const promedio = Number(inputPromedio.value);
  if (inputPromedio.value === "" || Number.isNaN(promedio) || promedio < 0 || promedio > 100) {
    mostrarError("Ingresa un promedio válido entre 0 y 100.");
    return;
  }

  btnCalcular.disabled = true;
  btnCalcular.textContent = "Calculando...";

  try {
    const respuesta = await fetch("/api/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        archivo: state.archivo,
        semestre_actual: state.semestreActual,
        promedio: promedio,
        modo: state.modo,
        cursos_aprobados: [...state.marcados],
        cursos_excluidos: state.cursos.filter(c => estaDescartado(c.codigo)).map(c => c.codigo),
        cursos_solo_vacaciones: [...state.noSemestre].filter(c => !state.noVacaciones.has(c)),
        cursos_solo_semestre: [...state.noVacaciones].filter(c => !state.noSemestre.has(c)),
        incluir_idiomas: checkIdiomas.checked,
        iniciar_en_vacaciones: state.iniciarEnVacaciones,
      }),
    });

    const datos = await respuesta.json();

    if (!respuesta.ok) {
      mostrarError(datos.detail || "No se pudo calcular la ruta.");
      return;
    }

    state.ultimoPlan = {
      datos: datos,
      promedio: promedio,
      modo: state.modo,
      puntoPartida: state.iniciarEnVacaciones
        ? `Vacaciones de semestre ${state.semestreActual - 1}`
        : `Semestre ${state.semestreActual}`,
      restricciones: Object.fromEntries(
        state.cursos
          .filter(c => state.noSemestre.has(c.codigo) !== state.noVacaciones.has(c.codigo))
          .map(c => [c.codigo, state.noSemestre.has(c.codigo) ? "Reservado para vacaciones" : "Reservado para semestre"])
      ),
    };

    renderizarResultado(datos);
    mostrarPantalla(pantallaResultado);
  } catch (error) {
    mostrarError("No se pudo conectar con el servidor. Verifica que esté corriendo.");
  } finally {
    btnCalcular.disabled = false;
    btnCalcular.textContent = "Calcular mi ruta";
  }
}

function mostrarError(texto) {
  mensajeError.textContent = texto;
  mensajeError.classList.remove("oculto");
}

function obtenerAvisos(datos) {
  const avisos = [];
  const objetivo = datos.objetivo_creditos;
  if (objetivo) {
    if (objetivo.social_humanistica_faltantes > 0) {
      avisos.push(`Faltan ${objetivo.social_humanistica_faltantes} crédito(s) de Social Humanística: con los cursos del área que no descartaste no se llega a los ${objetivo.social_humanistica_requeridos} créditos requeridos.`);
    }
    if (objetivo.creditos_faltantes > 0) {
      avisos.push(`Con los cursos disponibles en la malla faltan ${objetivo.creditos_faltantes} créditos para llegar al mínimo.`);
    }
    if (objetivo.idiomas_agregados_por_necesidad) {
      avisos.push("Se incluyeron idiomas técnicos porque, sin ellos, no alcanzaban los créditos requeridos.");
    }
  }
  if (datos.excluidos_obligatorios && datos.excluidos_obligatorios.length > 0) {
    avisos.push(`Excluiste (o dependen de lo que excluiste) ${datos.excluidos_obligatorios.length} curso(s) obligatorio(s): sin ellos no se puede cerrar pénsum.`);
  }
  if (datos.sin_oferta_vacacional && datos.sin_oferta_vacacional.length > 0) {
    const nombres = datos.sin_oferta_vacacional.map(c => `${c.codigo} ${c.nombre}`).join(", ");
    avisos.push(`No se ofrecen en vacaciones, así que no se pudieron reservar para ese periodo (se descartaron): ${nombres}.`);
  }
  return avisos;
}

async function descargarPdf() {
  const plan = state.ultimoPlan;
  if (!plan) return;

  const textoOriginal = btnDescargarPdf.textContent;
  btnDescargarPdf.disabled = true;
  btnDescargarPdf.textContent = "Generando PDF...";
  try {
    await exportarRutaPDF(plan.datos, {
      carrera: state.malla.carrera,
      pensum: `${state.malla.pensum} ${state.malla.vigente_desde}`,
      puntoPartida: plan.puntoPartida,
      modo: MODOS.find(m => m.valor === plan.modo)?.titulo ?? plan.modo,
      promedio: plan.promedio,
      avisos: obtenerAvisos(plan.datos),
      esObligatorio: codigo => (state.cursosPorCodigo.get(codigo)?.obligatorio ?? true),
      restriccion: codigo => plan.restricciones[codigo] || "",
    });
  } catch (error) {
    alert(error.message || "No se pudo generar el PDF.");
  } finally {
    btnDescargarPdf.disabled = false;
    btnDescargarPdf.textContent = textoOriginal;
  }
}

function renderizarResultado(datos) {
  const atrasadosCodigos = new Set(datos.atrasados_iniciales.map(c => c.codigo));

  resumenPlan.innerHTML = "";

  if (datos.atrasados_iniciales.length > 0) {
    const parrafoAtrasados = document.createElement("p");
    parrafoAtrasados.innerHTML = `<span class="etiqueta">Cursos atrasados detectados:</span>`;
    const lista = document.createElement("ul");
    lista.className = "lista-atrasados";
    datos.atrasados_iniciales.forEach(curso => {
      const item = document.createElement("li");
      item.textContent = `${curso.codigo} - ${curso.nombre}`;
      lista.appendChild(item);
    });
    resumenPlan.appendChild(parrafoAtrasados);
    resumenPlan.appendChild(lista);
  } else {
    const parrafoAlDia = document.createElement("p");
    parrafoAlDia.textContent = "Ibas al día: no había cursos atrasados pendientes al iniciar el plan.";
    resumenPlan.appendChild(parrafoAlDia);
  }

  if (datos.removidos_por_arrastre.length > 0) {
    const parrafoArrastre = document.createElement("p");
    parrafoArrastre.innerHTML = `<span class="etiqueta">Por arrastre de prerrequisitos, tampoco tendrías ganados:</span>`;
    const listaArrastre = document.createElement("ul");
    listaArrastre.className = "lista-atrasados";
    datos.removidos_por_arrastre.forEach(curso => {
      const item = document.createElement("li");
      item.textContent = `${curso.codigo} - ${curso.nombre}`;
      listaArrastre.appendChild(item);
    });
    resumenPlan.appendChild(parrafoArrastre);
    resumenPlan.appendChild(listaArrastre);
  }

  const parrafoDuracion = document.createElement("p");
  parrafoDuracion.innerHTML = `<span class="etiqueta">Duración normal del pénsum:</span> ${datos.duracion_normal_pensum} semestres.`;
  resumenPlan.appendChild(parrafoDuracion);

  const parrafoCierre = document.createElement("p");
  parrafoCierre.innerHTML = `<span class="etiqueta">Semestres a cursar desde ahora:</span> ${datos.semestres_cursados} (proyecta cierre en el semestre ${datos.semestre_estimado_cierre}).`;
  resumenPlan.appendChild(parrafoCierre);

  const parrafoEstado = document.createElement("p");
  if (datos.semestres_extra === 0) {
    parrafoEstado.innerHTML = `<span class="badge-ok">Cierras dentro del tiempo normal del pénsum (o antes).</span>`;
  } else {
    const plural = datos.semestres_extra === 1 ? "semestre" : "semestres";
    parrafoEstado.innerHTML = `<span class="badge-warn">Necesitarás ${datos.semestres_extra} ${plural} adicional(es) por encima de los ${datos.duracion_normal_pensum} semestres oficiales.</span>`;
  }
  resumenPlan.appendChild(parrafoEstado);

  const parrafoLimite = document.createElement("p");
  parrafoLimite.innerHTML = `<span class="etiqueta">Límite de créditos por semestre (según tu promedio):</span> ${datos.limite_creditos}.`;
  resumenPlan.appendChild(parrafoLimite);

  const objetivo = datos.objetivo_creditos;
  if (objetivo) {
    const parrafoCreditos = document.createElement("p");
    parrafoCreditos.innerHTML = `<span class="etiqueta">Créditos de la carrera con este plan:</span> ${objetivo.creditos_totales_plan} de ${objetivo.creditos_requeridos} requeridos.`;
    resumenPlan.appendChild(parrafoCreditos);

    const parrafoSH = document.createElement("p");
    parrafoSH.innerHTML = `<span class="etiqueta">Área Social Humanística:</span> ${objetivo.social_humanistica_en_plan} de ${objetivo.social_humanistica_requeridos} créditos (entre ganados y planificados).`;
    resumenPlan.appendChild(parrafoSH);

    obtenerAvisos(datos).forEach(texto => {
      const aviso = document.createElement("p");
      aviso.className = "aviso-plan";
      aviso.textContent = texto;
      resumenPlan.appendChild(aviso);
    });
  }

  gridResultado.innerHTML = "";
  Object.entries(datos.periodos).forEach(([nombrePeriodo, cursos]) => {
    const columna = document.createElement("div");
    columna.className = "columna-periodo";

    const titulo = document.createElement("h4");
    titulo.textContent = nombrePeriodo;
    columna.appendChild(titulo);

    const totalCreditos = cursos.reduce((suma, c) => suma + (c.creditos || 0), 0);
    const totales = document.createElement("div");
    totales.className = "totales";
    totales.textContent = `${cursos.length} cursos · ${totalCreditos} créditos`;
    columna.appendChild(totales);

    if (cursos.length === 0) {
      const vacio = document.createElement("p");
      vacio.className = "totales";
      vacio.textContent = "(sin cursos asignados)";
      columna.appendChild(vacio);
    }

    cursos.forEach(curso => {
      const esAtrasado = atrasadosCodigos.has(curso.codigo);
      const bloque = document.createElement("div");
      bloque.className = `curso-resultado${esAtrasado ? " atrasado" : ""}`;

      const codigo = document.createElement("span");
      codigo.className = "curso-codigo";
      codigo.textContent = `${curso.codigo} · ${curso.creditos ?? 0} créd.`;
      const cursoOriginal = state.cursosPorCodigo.get(curso.codigo);
      if (cursoOriginal && (cursoOriginal.obligatorio ?? true)) codigo.prepend(crearPuntoObligatorio());

      const nombre = document.createElement("span");
      nombre.textContent = curso.nombre;

      bloque.appendChild(codigo);
      bloque.appendChild(nombre);

      if (state.noSemestre.has(curso.codigo) !== state.noVacaciones.has(curso.codigo)) {
        const restriccion = document.createElement("span");
        restriccion.className = "etiqueta-tipo";
        restriccion.textContent = state.noSemestre.has(curso.codigo) ? "Reservado para vacaciones" : "Reservado para semestre";
        bloque.appendChild(restriccion);
      }

      const etiquetaTipo = TIPOS_ETIQUETA[curso.tipo];
      if (etiquetaTipo) {
        const tipo = document.createElement("span");
        tipo.className = "etiqueta-tipo";
        tipo.textContent = etiquetaTipo;
        bloque.appendChild(tipo);
      }

      if (esAtrasado) {
        const badge = document.createElement("span");
        badge.className = "badge-atrasado";
        badge.textContent = "Atrasado";
        bloque.appendChild(badge);
      }

      columna.appendChild(bloque);
    });

    gridResultado.appendChild(columna);
  });
}

function limpiarCampos() {
  state.noSemestre = new Set();
  state.noVacaciones = new Set();
  state.descartados = new Set();
  state.modoMarcado = "ganados";
  state.modo = "nivelarse";
  document.querySelector('input[name="modo-marcado"][value="ganados"]').checked = true;

  checkIdiomas.checked = false;
  inputPromedio.value = "";
  mensajeError.classList.add("oculto");
  mensajeError.textContent = "";

  resumenPlan.innerHTML = "";
  gridResultado.innerHTML = "";

  construirSelectSemestre();
  renderizarOpcionesModo();
  mostrarPantalla(pantallaFormulario);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

btnLimpiar.addEventListener("click", limpiarCampos);
btnLimpiarResultado.addEventListener("click", limpiarCampos);

btnCalcular.addEventListener("click", calcularRuta);
btnDescargarPdf.addEventListener("click", descargarPdf);

btnVolverCarreras.addEventListener("click", () => {
  mostrarPantalla(pantallaCarreras);
});

btnVolverFormulario.addEventListener("click", () => {
  mostrarPantalla(pantallaFormulario);
});

cargarCarreras();