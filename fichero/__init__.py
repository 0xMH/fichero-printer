"""Fichero D11s thermal label printer - BLE, Classic Bluetooth and USB interface."""

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

from fichero.usb import USBClient, discover_usb

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
    "USBClient",
    "discover_usb",
]
