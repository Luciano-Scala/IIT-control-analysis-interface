# IIT-control-analysis-interface

A modular Python desktop application built with **PySide6** designed for real-time data acquisition from **Arduino** hardware and advanced post-processing of mechanical testing data (instrumented indentation and hardness testing).

---

## Key Features

* **Real-time Data Acquisition:** Multithreaded serial communication (`QThread`) with Arduino for sensor reading and motion control.
* **Signal Processing:** Gaussian filtering, outlier removal, curve alignment, and state segmentation.
* **Mechanical Characterization:** Automatic calculation of mechanical properties using Oliver-Pharr, Ludwik, and Hollomon models.
* **Interactive Visualization:** Integrated Matplotlib plots (`FigureCanvasQTAgg`) for real-time force-displacement curves.
* **Automated Reporting:** PDF report generation for indentation and hardness test results.

---

## Architecture Overview

The application follows a clean **MVC / MVVM pattern** to decouple UI, processing algorithms, and hardware interaction:

```text
IITCAI_app/
├── main.py                     # Entrypoint
├── config.py                   # App configuration & constants
├── core/                       # Core logic (UI-independent)
│   ├── hardware/               # Arduino serial communication (QThread)
│   └── processing/             # Signal filtering, segmentation & mathematical models
├── ui/                         # PySide6 presentation layer
│   ├── main_window.py          # Main container (QTabWidget)
│   ├── tabs/                   # Modular UI tabs (Acquisition, Analysis, Reports)
│   ├── dialogs/                # Modal dialogs for inputs
│   └── widgets/                # Matplotlib canvas wrappers & custom controls
└── utils/                      # PDF export & logging tools
```
## Requirements
* Python 3.10+
* PySide6
* NumPy
* SciPy
* Matplotlib
* PySerial

## Quick Start
Clone the repository:

Bash
git clone [https://github.com/Luciano-Scala/IIT-control-analysis-interface.git](https://github.com/Luciano-Scala/IIT-control-analysis-interface.git)
cd IIT-control-analysis-interface
Install dependencies:

Bash
pip install -r requirements.txt
Run the application:

Bash
python main.py
