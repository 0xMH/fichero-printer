"""Fichero D11s thermal label printer - BLE + Classic Bluetooth interface."""

from fichero.printer import (
    RFCOMM_CHANNEL,
    PrinterClient,
    PrinterError,
    PrinterNotFound,
    PrinterNotReady,
    PrinterStatus,
    PrinterTimeout,
    RFCOMMClient,
    connect,
)

__all__ = [
    "RFCOMM_CHANNEL",
    "PrinterClient",
    "PrinterError",
    "PrinterNotFound",
    "PrinterNotReady",
    "PrinterStatus",
    "PrinterTimeout",
    "RFCOMMClient",
    "connect",
]
