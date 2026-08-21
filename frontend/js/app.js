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
  modo: "nivelarse",
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
const mensajeError = document.getElementById("mensaje-error");

const btnVolverCarreras = document.getElementById("btn-volver-carreras");
const btnVolverFormulario = document.getElementById("btn-volver-formulario");
const resumenPlan = document.getElementById("resumen-plan");
const gridResultado = document.getElementById("grid-resultado");

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
    opcion.value = numero;
    opcion.textContent = `Semestre ${numero}`;
    selectSemestre.appendChild(opcion);
  });
  state.semestreActual = semestres[0];
  selectSemestre.value = state.semestreActual;
  recalcularMarcadosPorDefecto();
  renderizarGridCursos();
}

selectSemestre.addEventListener("change", () => {
  state.semestreActual = Number(selectSemestre.value);
  recalcularMarcadosPorDefecto();
  renderizarGridCursos();
});

function recalcularMarcadosPorDefecto() {
  state.marcados = new Set(
    state.cursos
      .filter(c => (c.obligatorio ?? true) && c.semestre < state.semestreActual)
      .map(c => c.codigo)
  );
}

function renderizarGridCursos() {
  gridCursos.innerHTML = "";
  const semestres = [...new Set(state.cursos.map(c => c.semestre).filter(s => s != null))].sort((a, b) => a - b);

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
        bloque.className = `curso ${marcado ? "curso-marcado" : "curso-pendiente"}${esOptativo ? " curso-optativo" : ""}`;

        const codigo = document.createElement("span");
        codigo.className = "curso-codigo";
        codigo.textContent = curso.codigo;

        const nombre = document.createElement("span");
        nombre.textContent = curso.nombre;

        bloque.appendChild(codigo);
        bloque.appendChild(nombre);
        bloque.addEventListener("click", () => alternarMarcado(curso.codigo, bloque));

        columna.appendChild(bloque);
      });

    gridCursos.appendChild(columna);
  });
}

function alternarMarcado(codigo, bloque) {
  if (state.marcados.has(codigo)) {
    state.marcados.delete(codigo);
    bloque.classList.remove("curso-marcado");
    bloque.classList.add("curso-pendiente");
  } else {
    state.marcados.add(codigo);
    bloque.classList.remove("curso-pendiente");
    bloque.classList.add("curso-marcado");
  }
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
      }),
    });

    const datos = await respuesta.json();

    if (!respuesta.ok) {
      mostrarError(datos.detail || "No se pudo calcular la ruta.");
      return;
    }

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

      const nombre = document.createElement("span");
      nombre.textContent = curso.nombre;

      bloque.appendChild(codigo);
      bloque.appendChild(nombre);

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

btnCalcular.addEventListener("click", calcularRuta);

btnVolverCarreras.addEventListener("click", () => {
  mostrarPantalla(pantallaCarreras);
});

btnVolverFormulario.addEventListener("click", () => {
  mostrarPantalla(pantallaFormulario);
});

cargarCarreras();
