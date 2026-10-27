"""Navegador interno do M-Search+ (Qt WebEngine).

Se o pacote PyQt6-WebEngine não estiver instalado, WEBENGINE_AVAILABLE é False e o M-Search+ continua funcionando
(sem navegador interno). Instale com:  pip install PyQt6-WebEngine
"""
try:  # importar ANTES de criar o QApplication
    from PyQt6 import QtWebEngineCore as _core, QtWebEngineWidgets as _widgets  # noqa: F401
    WEBENGINE_AVAILABLE = True
    WEBENGINE_ERROR = ""
except Exception as _exc:  # ImportError ou erro de DLL/Qt
    WEBENGINE_AVAILABLE = False
    WEBENGINE_ERROR = str(_exc)
