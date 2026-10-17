"""Optional PyUSB transport for the D11s (09c5:0200).

Replies to proprietary commands arrive on the bulk-IN endpoint with the same
bytes as Bluetooth notifications. Blocking libusb operations run in worker
threads, serialized through cancellation; a reader thread delivers replies.
"""

import asyncio
import errno
import sys
import threading
import warnings

from fichero.printer import (
    CHUNK_SIZE_USB,
    DELAY_CHUNK_GAP_USB,
    PrinterError,
    PrinterNotFound,
    PrinterTimeout,
)

USB_VID = 0x09C5
USB_PID = 0x0200
READ_SIZE = 512
READ_POLL_MS = 100  # bounds how long closing waits for the reader thread
DRAIN_TIMEOUT_MS = 50


def _modules():
    try:
        import usb.core
        import usb.util
    except ImportError as exc:
        raise PrinterError(
            "USB requires PyUSB: install with uv sync --extra usb"
        ) from exc
    return usb.core, usb.util


def _error(exc):
    # PyUSB maps libusb errors to the platform's errno values.
    core, _ = _modules()
    code = getattr(exc, "errno", None)
    if code == errno.EACCES:
        return PrinterError(
            "USB permission denied; configure the D11s udev rule (see README)"
        )
    if code == errno.EBUSY:
        return PrinterError(
            "USB interface busy; close other clients and check CUPS/usblp contention"
        )
    if code == errno.ETIMEDOUT or isinstance(exc, core.USBTimeoutError):
        return PrinterTimeout(
            "USB transfer timed out; print outcome is unknown (do not retry blindly)"
        )
    if isinstance(exc, core.NoBackendError):
        return PrinterError("USB backend unavailable; install libusb (see README)")
    return PrinterError(f"USB operation failed: {exc}")


async def _worker(func, *args):
    # A cancelled to_thread call keeps running. Wait for it through any number
    # of cancellations so cleanup never releases the handle mid-transfer, then
    # re-raise the cancellation in preference to any error the worker produced.
    task = asyncio.ensure_future(asyncio.to_thread(func, *args))
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            pass  # surfaced below through task.result()
    if cancelled:
        if not task.cancelled():
            task.exception()  # mark retrieved; cancellation takes precedence
        raise asyncio.CancelledError
    return task.result()


def _serial(device):
    try:
        return device.serial_number
    except ValueError as exc:
        raise PrinterError(
            "Cannot read USB serial descriptor; check udev permissions "
            "and device connection (see README)"
        ) from exc


def _devices(core):
    try:
        return list(core.find(find_all=True, idVendor=USB_VID, idProduct=USB_PID))
    except (core.USBError, core.NoBackendError) as exc:
        raise _error(exc) from exc


async def discover_usb() -> list[dict]:
    """Return serial/bus/address records without claiming printer interfaces."""

    def scan():
        core, util = _modules()
        devices = _devices(core)
        try:
            return [
                {"serial": _serial(d), "bus": d.bus, "address": d.address}
                for d in devices
            ]
        except (core.USBError, core.NoBackendError) as exc:
            raise _error(exc) from exc
        finally:
            for device in devices:
                util.dispose_resources(device)

    return await _worker(scan)


class USBClient:
    """Async transport adapter with the write_gatt_char/start_notify interface."""

    is_usb = True
    chunk_size = CHUNK_SIZE_USB
    chunk_delay = DELAY_CHUNK_GAP_USB

    def __init__(self, serial: str | None = None, timeout: int = 5000):
        if timeout <= 0:
            raise ValueError("USB timeout must be positive (milliseconds)")
        self.serial = serial
        self.timeout = timeout
        self._device = None
        self._interface = None
        self._endpoint = None
        self._in_endpoint = None
        self._detached = False
        self._claimed = False
        self._reader = None
        self._reader_stop = threading.Event()
        self._lock = asyncio.Lock()

    def _open(self):
        core, util = _modules()
        devices = _devices(core)
        try:
            matches = [
                d for d in devices if self.serial is None or _serial(d) == self.serial
            ]
            if not matches:
                raise PrinterNotFound("No matching D11s USB printer (09c5:0200)")
            if len(matches) > 1:
                raise PrinterError(
                    "Multiple D11s USB printers; select one with --serial"
                )
            self._device = device = matches[0]
            # Do not reset an already configured device (which can disrupt CUPS).
            cfg = device.get_active_configuration()
            candidates = []
            for interface in cfg:
                if (
                    interface.bInterfaceClass,
                    interface.bInterfaceSubClass,
                    interface.bInterfaceProtocol,
                    interface.bAlternateSetting,
                ) != (7, 1, 2, 0):
                    continue
                endpoints = [ep for ep in interface if ep.bmAttributes & 3 == 2]
                outputs = [ep for ep in endpoints if not ep.bEndpointAddress & 0x80]
                inputs = [ep for ep in endpoints if ep.bEndpointAddress & 0x80]
                if len(outputs) == 1 and inputs:
                    candidates.append(
                        (
                            interface.bInterfaceNumber,
                            outputs[0].bEndpointAddress,
                            inputs[0].bEndpointAddress,
                        )
                    )
            if len(candidates) != 1:
                raise PrinterError(
                    "Expected one bidirectional USB Printer Class interface with bulk endpoints"
                )
            self._interface, self._endpoint, self._in_endpoint = candidates[0]
            try:
                active = device.is_kernel_driver_active(self._interface)
            except NotImplementedError:
                active = False
            if active:
                device.detach_kernel_driver(self._interface)
                self._detached = True
            util.claim_interface(device, self._interface)
            self._claimed = True
            self._drain(core)
        except (core.USBError, core.NoBackendError) as exc:
            raise _error(exc) from exc
        finally:
            for device in devices:
                if device is not self._device:
                    util.dispose_resources(device)

    def _drain(self, core):
        # Unread replies survive closing and usblp rebinding; discard them so
        # they are not taken as replies to this session's commands.
        for _ in range(64):
            try:
                self._device.read(self._in_endpoint, READ_SIZE, timeout=DRAIN_TIMEOUT_MS)
            except core.USBTimeoutError:
                return

    def _close(self):
        if self._device is None:
            return
        _, util = _modules()
        device, self._device = self._device, None
        errors = []
        try:
            # Stop reading before the interface is released.
            if self._reader is not None:
                self._reader_stop.set()
                self._reader.join()
                self._reader = None
            if self._claimed:
                try:
                    util.release_interface(device, self._interface)
                except Exception as exc:
                    errors.append(exc)
            if self._detached:
                try:
                    device.attach_kernel_driver(self._interface)
                except Exception as exc:
                    errors.append(exc)
        finally:
            self._claimed = self._detached = False
            try:
                util.dispose_resources(device)
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise _error(errors[0])

    async def __aenter__(self):
        try:
            await _worker(self._open)
        except BaseException:
            await self.__aexit__(*sys.exc_info())
            raise
        return self

    async def __aexit__(self, exc_type, exc, tb):
        async with self._lock:
            try:
                await _worker(self._close)
            except PrinterError as cleanup_error:
                if exc_type is None:
                    raise
                warnings.warn(f"USB cleanup failed: {cleanup_error}", RuntimeWarning)

    async def start_notify(self, _uuid, callback):
        if self._device is None:
            raise PrinterError("USB transport is not connected")
        core, _ = _modules()
        loop = asyncio.get_running_loop()
        device, endpoint, stop = self._device, self._in_endpoint, self._reader_stop

        def read_loop():
            while not stop.is_set():
                try:
                    data = device.read(endpoint, READ_SIZE, timeout=READ_POLL_MS)
                except core.USBTimeoutError:
                    continue
                except (core.USBError, core.NoBackendError):
                    return  # disconnected; pending replies time out
                if data:
                    try:
                        loop.call_soon_threadsafe(callback, None, bytearray(data))
                    except RuntimeError:
                        return  # event loop closed

        stop.clear()
        self._reader = threading.Thread(
            target=read_loop, name="fichero-usb-reader", daemon=True
        )
        self._reader.start()

    async def write_gatt_char(self, _uuid, data, response=False):
        def write():
            if self._device is None:
                raise PrinterError("USB transport is not connected")
            core, _ = _modules()
            try:
                written = self._device.write(self._endpoint, data, timeout=self.timeout)
            except (core.USBError, core.NoBackendError) as exc:
                raise _error(exc) from exc
            if written != len(data):
                raise PrinterError(
                    f"Incomplete USB write ({written}/{len(data)} bytes); print outcome unknown"
                )

        async with self._lock:
            await _worker(write)
