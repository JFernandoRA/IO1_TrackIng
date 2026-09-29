const PDF_MARGEN = 14;
const PDF_COLOR_AZUL = [24, 95, 165];
const PDF_COLOR_VACACIONES = [186, 117, 23];
const PDF_COLOR_GRIS_CLARO = [241, 239, 232];
const PDF_COLOR_TEXTO = [44, 44, 42];
const PDF_COLOR_ATRASADO = [163, 45, 45];

const PDF_ETIQUETAS_TIPO = {
  social_humanistica: "Social Humanística",
  idioma: "Idioma técnico",
  optativo: "Optativo",
};

function pdfNombrePeriodo(nombre) {
  return String(nombre).replace(/_/g, " ");
}

function pdfNombreArchivo(carrera) {
  const base = String(carrera || "ruta")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-zA-Z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  const hoy = new Date();
  const fecha = `${hoy.getFullYear()}-${String(hoy.getMonth() + 1).padStart(2, "0")}-${String(hoy.getDate()).padStart(2, "0")}`;
  return `TrackIng_${base}_${fecha}.pdf`;
}

function pdfFechaLarga() {
  const hoy = new Date();
  return `${String(hoy.getDate()).padStart(2, "0")}/${String(hoy.getMonth() + 1).padStart(2, "0")}/${hoy.getFullYear()}`;
}

function pdfDetalleCurso(curso, atrasados, contexto) {
  const partes = [];
  const obligatorio = contexto.esObligatorio(curso.codigo);
  const etiquetaTipo = PDF_ETIQUETAS_TIPO[curso.tipo];

  if (obligatorio) {
    partes.push(curso.tipo === "social_humanistica" ? "Obligatorio (Social Humanística)" : "Obligatorio");
  } else {
    partes.push(etiquetaTipo || "Optativo");
  }

  const restriccion = contexto.restriccion(curso.codigo);
  if (restriccion) partes.push(restriccion);
  if (atrasados.has(curso.codigo)) partes.push("Atrasado");
  return partes.join(" · ");
}

function pdfFilasResumen(datos, contexto) {
  const filas = [];
  filas.push(["Punto de partida", contexto.puntoPartida]);
  filas.push(["Objetivo", contexto.modo]);
  filas.push([
    "Promedio acumulado",
    `${contexto.promedio} (límite de ${datos.limite_creditos} créditos por semestre)`,
  ]);
  filas.push(["Duración normal del pénsum", `${datos.duracion_normal_pensum} semestres`]);
  filas.push([
    "Semestres a cursar desde ahora",
    `${datos.semestres_cursados} (cierre proyectado en el semestre ${datos.semestre_estimado_cierre})`,
  ]);

  if (datos.semestres_extra === 0) {
    filas.push(["Estado", "Cierras dentro del tiempo normal del pénsum (o antes)."]);
  } else {
    filas.push([
      "Estado",
      `Necesitarás ${datos.semestres_extra} semestre(s) adicional(es) por encima de los ${datos.duracion_normal_pensum} semestres oficiales.`,
    ]);
  }

  const objetivo = datos.objetivo_creditos;
  if (objetivo) {
    filas.push(["Créditos con este plan", `${objetivo.creditos_totales_plan} de ${objetivo.creditos_requeridos} requeridos`]);
    filas.push([
      "Área Social Humanística",
      `${objetivo.social_humanistica_en_plan} de ${objetivo.social_humanistica_requeridos} créditos (entre ganados y planificados)`,
    ]);
  }

  if (datos.atrasados_iniciales && datos.atrasados_iniciales.length > 0) {
    filas.push([
      "Cursos atrasados",
      datos.atrasados_iniciales.map(c => `${c.codigo} - ${c.nombre}`).join("\n"),
    ]);
  } else {
    filas.push(["Cursos atrasados", "Ninguno: ibas al día al iniciar el plan."]);
  }

  if (datos.removidos_por_arrastre && datos.removidos_por_arrastre.length > 0) {
    filas.push([
      "Sin ganar por arrastre de prerrequisitos",
      datos.removidos_por_arrastre.map(c => `${c.codigo} - ${c.nombre}`).join("\n"),
    ]);
  }
  return filas;
}

function construirRutaPDF(datos, contexto, logo) {
  const JsPDF = window.jspdf && window.jspdf.jsPDF;
  if (!JsPDF) {
    throw new Error("No se pudo cargar la librería de PDF. Revisa tu conexión a internet e intenta de nuevo.");
  }

  const doc = new JsPDF({ unit: "mm", format: "a4" });
  if (typeof doc.autoTable !== "function") {
    throw new Error("No se pudo cargar el complemento de tablas del PDF. Revisa tu conexión a internet e intenta de nuevo.");
  }

  const anchoPagina = doc.internal.pageSize.getWidth();
  const altoPagina = doc.internal.pageSize.getHeight();
  const atrasados = new Set((datos.atrasados_iniciales || []).map(c => c.codigo));

  doc.setFillColor(...PDF_COLOR_AZUL);
  doc.rect(0, 0, anchoPagina, 24, "F");
  let xTitulo = PDF_MARGEN;
  if (logo) {
    try {
      doc.addImage(logo, "PNG", PDF_MARGEN, 4, 16, 16);
      xTitulo = PDF_MARGEN + 20;
    } catch (error) {
      xTitulo = PDF_MARGEN;
    }
  }
  doc.setTextColor(255, 255, 255);
  doc.setFont("helvetica", "bold");
  doc.setFontSize(17);
  doc.text("TrackIng", xTitulo, 12);
  doc.setFont("helvetica", "normal");
  doc.setFontSize(10);
  doc.text("Ruta académica hasta el cierre de pénsum", xTitulo, 18.5);
  doc.setFontSize(9);
  doc.text(`Generado el ${pdfFechaLarga()}`, anchoPagina - PDF_MARGEN, 12, { align: "right" });

  doc.setTextColor(...PDF_COLOR_TEXTO);
  doc.setFont("helvetica", "bold");
  doc.setFontSize(13);
  const lineasCarrera = doc.splitTextToSize(contexto.carrera || "", anchoPagina - PDF_MARGEN * 2);
  doc.text(lineasCarrera, PDF_MARGEN, 33);
  let y = 33 + lineasCarrera.length * 5.5;
  doc.setFont("helvetica", "normal");
  doc.setFontSize(9.5);
  doc.setTextColor(110, 110, 105);
  doc.text(contexto.pensum || "", PDF_MARGEN, y);
  y += 5;

  doc.autoTable({
    startY: y,
    body: pdfFilasResumen(datos, contexto),
    theme: "plain",
    margin: { left: PDF_MARGEN, right: PDF_MARGEN, top: 16, bottom: 16 },
    styles: { font: "helvetica", fontSize: 9, cellPadding: { top: 1.2, bottom: 1.2, left: 2, right: 2 }, textColor: PDF_COLOR_TEXTO, valign: "top" },
    columnStyles: { 0: { fontStyle: "bold", cellWidth: 58, textColor: PDF_COLOR_AZUL } },
    alternateRowStyles: { fillColor: PDF_COLOR_GRIS_CLARO },
  });
  y = doc.lastAutoTable.finalY + 4;

  const avisos = contexto.avisos || [];
  if (avisos.length > 0) {
    doc.setFont("helvetica", "normal");
    doc.setFontSize(9);
    doc.setTextColor(...PDF_COLOR_VACACIONES);
    avisos.forEach(aviso => {
      const lineas = doc.splitTextToSize(`Aviso: ${aviso}`, anchoPagina - PDF_MARGEN * 2);
      if (y + lineas.length * 4.2 > altoPagina - 16) {
        doc.addPage();
        y = 16;
      }
      doc.text(lineas, PDF_MARGEN, y);
      y += lineas.length * 4.2 + 1.5;
    });
    y += 2;
  }

  Object.entries(datos.periodos).forEach(([nombrePeriodo, cursos]) => {
    const esVacaciones = !/^semestre/i.test(nombrePeriodo);
    const colorPeriodo = esVacaciones ? PDF_COLOR_VACACIONES : PDF_COLOR_AZUL;
    const totalCreditos = cursos.reduce((suma, c) => suma + (c.creditos || 0), 0);
    const resumenPeriodo = `${cursos.length} ${cursos.length === 1 ? "curso" : "cursos"} · ${totalCreditos} créditos`;

    const alturaEstimada = (Math.max(cursos.length, 1) + 2) * 7;
    if (cursos.length <= 9 && y + alturaEstimada > altoPagina - 16) {
      doc.addPage();
      y = 16;
    }

    const cuerpo = cursos.length === 0
      ? [[{ content: "(sin cursos asignados)", colSpan: 4, styles: { fontStyle: "italic", textColor: [110, 110, 105] } }]]
      : cursos.map(curso => [
        curso.codigo,
        curso.nombre,
        String(curso.creditos ?? 0),
        pdfDetalleCurso(curso, atrasados, contexto),
      ]);

    const filaTituloPeriodo = [
      { content: `${pdfNombrePeriodo(nombrePeriodo)}  ·  ${resumenPeriodo}`, colSpan: 4, styles: { fillColor: colorPeriodo, textColor: [255, 255, 255], fontSize: 10, halign: "left" } },
    ];

    doc.autoTable({
      startY: y,
      head: cursos.length === 0 ? [filaTituloPeriodo] : [
        filaTituloPeriodo,
        [
          { content: "Código", styles: { fillColor: PDF_COLOR_GRIS_CLARO, textColor: PDF_COLOR_TEXTO } },
          { content: "Curso", styles: { fillColor: PDF_COLOR_GRIS_CLARO, textColor: PDF_COLOR_TEXTO } },
          { content: "Créd.", styles: { fillColor: PDF_COLOR_GRIS_CLARO, textColor: PDF_COLOR_TEXTO, halign: "center" } },
          { content: "Detalle", styles: { fillColor: PDF_COLOR_GRIS_CLARO, textColor: PDF_COLOR_TEXTO } },
        ],
      ],
      body: cuerpo,
      theme: "grid",
      margin: { left: PDF_MARGEN, right: PDF_MARGEN, top: 16, bottom: 16 },
      styles: { font: "helvetica", fontSize: 8.5, cellPadding: 1.6, lineColor: [210, 208, 200], lineWidth: 0.1, textColor: PDF_COLOR_TEXTO },
      headStyles: { fontStyle: "bold" },
      columnStyles: cursos.length === 0 ? {} : {
        0: { cellWidth: 20 },
        2: { cellWidth: 14, halign: "center" },
        3: { cellWidth: 62 },
      },
      didParseCell: data => {
        if (data.section === "body" && data.column.index === 3 && /Atrasado/.test(String(data.cell.raw))) {
          data.cell.styles.textColor = PDF_COLOR_ATRASADO;
        }
      },
    });
    y = doc.lastAutoTable.finalY + 5;
  });

  const totalPaginas = doc.internal.getNumberOfPages();
  for (let pagina = 1; pagina <= totalPaginas; pagina++) {
    doc.setPage(pagina);
    doc.setFont("helvetica", "normal");
    doc.setFontSize(8);
    doc.setTextColor(140, 140, 135);
    doc.text(`TrackIng · Página ${pagina} de ${totalPaginas}`, anchoPagina / 2, altoPagina - 8, { align: "center" });
  }

  return doc;
}

async function pdfCargarImagen(url) {
  try {
    const respuesta = await fetch(url);
    if (!respuesta.ok) return null;
    const blob = await respuesta.blob();
    return await new Promise(resolve => {
      const lector = new FileReader();
      lector.onload = () => resolve(lector.result);
      lector.onerror = () => resolve(null);
      lector.readAsDataURL(blob);
    });
  } catch (error) {
    return null;
  }
}

async function exportarRutaPDF(datos, contexto) {
  const logo = await pdfCargarImagen("img/logo_trackIng_icono.png");
  const doc = construirRutaPDF(datos, contexto, logo);
  doc.save(pdfNombreArchivo(contexto.carrera));
}
