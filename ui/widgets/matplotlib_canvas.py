"""
ui/widgets/matplotlib_canvas.py
"""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget


class MatplotlibCanvas(FigureCanvasQTAgg):
    """``FigureCanvasQTAgg`` con una Figure ya creada y configurada para
    expandirse dentro de un layout de Qt."""

    def __init__(
        self,
        nrows: int = 1,
        ncols: int = 1,
        figsize: Tuple[float, float] = (5, 4),
        dpi: int = 100,
        tight_layout: bool = True,
    ):
        self.fig = Figure(figsize=figsize, dpi=dpi, tight_layout=tight_layout)
        if nrows * ncols > 0:
            axes = self.fig.subplots(nrows, ncols)
            self.axes = axes if nrows * ncols > 1 else [axes]
        else:
            self.axes = []

        super().__init__(self.fig)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.updateGeometry()

    def ax(self, index: int = 0):
        """Acceso cómodo al subplot ``index`` (equivalente a lo que en
        el original era ``self.ax`` / ``self.ax1`` / ``self.ax2``)."""
        return self.axes[index]

    def clear(self, index: Optional[int] = None) -> None:
        """Limpia uno o todos los subplots, preservando ejes/labels que
        se vuelvan a configurar tras el clear."""
        targets = self.axes if index is None else [self.axes[index]]
        for a in targets:
            a.clear()

    def redraw(self) -> None:
        """Redibuja el canvas. Preferir ``draw_idle`` en vez de
        ``draw`` cuando se llama muy seguido (p.ej. adquisición en vivo
        a alta frecuencia), para no saturar el loop de eventos de Qt."""
        self.draw_idle()


class MatplotlibWidget(QWidget):
    """Widget contenedor: canvas + barra de herramientas opcional.

    Uso típico dentro de una pestaña::

        self.plot_widget = MatplotlibWidget(nrows=2, ncols=1, toolbar=True)
        layout.addWidget(self.plot_widget)
        ax_carga, ax_lvdt = self.plot_widget.axes

        ax_carga.plot(t, carga)
        self.plot_widget.redraw()
    """

    def __init__(
        self,
        nrows: int = 1,
        ncols: int = 1,
        figsize: Tuple[float, float] = (5, 4),
        dpi: int = 100,
        toolbar: bool = False,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)

        self.canvas = MatplotlibCanvas(nrows=nrows, ncols=ncols, figsize=figsize, dpi=dpi)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.toolbar: Optional[NavigationToolbar2QT] = None
        if toolbar:
            self.toolbar = NavigationToolbar2QT(self.canvas, self)
            layout.addWidget(self.toolbar)

        layout.addWidget(self.canvas)

    # ------------------------------------------------------------------
    # Delegados convenientes hacia el canvas
    # ------------------------------------------------------------------
    @property
    def figure(self) -> Figure:
        return self.canvas.fig

    @property
    def axes(self):
        return self.canvas.axes

    def ax(self, index: int = 0):
        return self.canvas.ax(index)

    def clear(self, index: Optional[int] = None) -> None:
        self.canvas.clear(index)

    def redraw(self) -> None:
        self.canvas.redraw()

    def plot_line(
        self,
        x: Sequence[float],
        y: Sequence[float],
        index: int = 0,
        clear_first: bool = False,
        **plot_kwargs,
    ) -> None:
        """Atajo para el caso más común: graficar una línea en el
        subplot ``index`` y redibujar."""
        a = self.ax(index)
        if clear_first:
            a.clear()
        a.plot(x, y, **plot_kwargs)
        self.redraw()