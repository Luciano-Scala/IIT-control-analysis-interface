"""
ui/main_window.py
"""

from __future__ import annotations

from PySide6.QtWidgets import QFileDialog, QMainWindow, QMessageBox, QTabWidget

import config
from ui.tabs.acquisition_tab import AcquisitionTab
from ui.tabs.analysis_tab import AnalysisTab
from ui.tabs.hardness_tab import HardnessTab
from ui.tabs.report_tab import ReportTab
from ui.tabs.results_tab import ResultsTab
from utils.excel_exporter import DatosInforme, ImprontaRow, IndentacionRow, exportar_informe
from utils.logger import get_logger

log = get_logger()


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(config.APP_TITLE)
        self.resize(1280, 900)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.acquisition_tab = AcquisitionTab()
        self.tabs.addTab(self.acquisition_tab, "Adquisición de Datos")

        self.analysis_tab = AnalysisTab()
        self.tabs.addTab(self.analysis_tab, "Análisis CSV")

        self.results_tab = ResultsTab()
        self.tabs.addTab(self.results_tab, "Resultados Finales")
        self.analysis_tab.resultado_calculado.connect(self._on_resultado_calculado)

        self.report_tab = ReportTab()
        self.tabs.addTab(self.report_tab, "Pre - Informe (Indentación)")
        self.analysis_tab.curva_informe_lista.connect(self.report_tab.agregar_curva)
        self.analysis_tab.resultado_informe_listo.connect(self.report_tab.agregar_resultado)
        self.acquisition_tab.client_data_changed.connect(self.report_tab.set_client_info)
        self.report_tab.exportar_solicitado.connect(self._exportar_informe_excel)

        self.hardness_tab = HardnessTab()
        self.tabs.addTab(self.hardness_tab, "Pre - Informe (Dureza)")
        self.analysis_tab.resultado_dureza_listo.connect(self.hardness_tab.agregar_impronta)
        self.acquisition_tab.client_data_changed.connect(self.hardness_tab.set_client_info)

    def _on_resultado_calculado(self, resultado, csv_path: str) -> None:
        """Réplica de ``self.notebook.select(self.page_results)`` en
        ``recalcular``: al terminar el cálculo en Análisis, se muestra
        el resultado y se cambia automáticamente a esta pestaña."""
        self.results_tab.mostrar_resultado(resultado, csv_path)
        self.tabs.setCurrentWidget(self.results_tab)

    def _exportar_informe_excel(self) -> None:
        """Réplica de ``self.analysis_tab.curva_informe_lista`` +
        ``resultado_informe_listo`` que finalmente se materializan acá:
        junta los datos de ``ReportTab`` (cliente, curvas, resultados
        σy/UTS) y ``HardnessTab`` (improntas Brinell) y llama a
        ``utils/excel_exporter.py`` para completar el formulario
        FM-086. Ninguna pestaña conoce a la otra directamente — esta
        orquestación es responsabilidad de la ventana principal."""
        datos_generales = self.report_tab.obtener_datos_generales()
        filas_indentacion = self.report_tab.obtener_resultados_para_exportacion()
        filas_dureza = self.hardness_tab.obtener_improntas_para_exportacion()
        grafico_png = self.report_tab.render_grafico_png()

        if not filas_indentacion and not filas_dureza:
            QMessageBox.warning(
                self,
                "Atención",
                "No hay indentaciones ni improntas de dureza cargadas en el preinforme.",
            )
            return

        datos = DatosInforme(
            cliente=datos_generales["cliente"],
            solicitud=datos_generales["solicitud"],
            fecha=datos_generales["fecha"],
            muestra=datos_generales["muestra"],
            lugar=datos_generales["lugar"],
            coordenadas=datos_generales["coordenadas"],
            temperatura=datos_generales["temperatura"],
            comentario=datos_generales["comentario"],
            indentaciones=[IndentacionRow(*fila) for fila in filas_indentacion],
            improntas=[ImprontaRow(*fila) for fila in filas_dureza],
            grafico_png_bytes=grafico_png,
        )

        nombre_sugerido = f"FM-086_{datos_generales['muestra'] or 'informe'}.xlsx"
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Guardar Pre-Informe de Indentación", nombre_sugerido,
            "Archivos Excel (*.xlsx);;Todos los archivos (*.*)",
        )
        if not file_path:
            return
        if not file_path.lower().endswith(".xlsx"):
            file_path += ".xlsx"

        try:
            exportar_informe(datos, file_path)
            QMessageBox.information(self, "Informe exportado", f"Informe guardado en:\n{file_path}")
        except Exception as exc:  # noqa: BLE001
            log.exception("Error exportando el informe a Excel")
            QMessageBox.critical(self, "Error", f"No se pudo exportar el informe:\n{exc}")

    def closeEvent(self, event) -> None:
        """Asegura que el QThread de lectura serie se detenga antes de
        cerrar la aplicación (evita el warning/crash de Qt por hilos
        vivos al destruir la ventana)."""
        self.acquisition_tab.shutdown()
        self.analysis_tab.shutdown()
        super().closeEvent(event)