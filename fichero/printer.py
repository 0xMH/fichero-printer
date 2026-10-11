"""
Fichero / D11s thermal label printer - BLE + Classic Bluetooth interface.

Protocol reverse-engineered from decompiled Fichero APK (com.lj.fichero).
Device class: AiYinNormalDevice (LuckPrinter SDK)
96px wide printhead (12 bytes/row), 203 DPI, prints 1-bit raster images.
"""

import asyncio
import sys
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager

from bleak import BleakClient, BleakGATTCharacteristic, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.exc import BleakDBusError

# --- RFCOMM (Classic Bluetooth) support - Linux + Windows (Python 3.9+) ---

_RFCOMM_AVAILABLE = False
if sys.platform in ("linux", "win32"):
    import socket as _socket

    _RFCOMM_AVAILABLE = hasattr(_socket, "AF_BLUETOOTH")

RFCOMM_CHANNEL = 1

# --- BLE identifiers ---

PRINTER_NAME_PREFIXES = ("FICHERO", "D11s_")

# Using the 18f0 service (any of the four BLE UART services work)
WRITE_UUID = "00002af1-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID = "00002af0-0000-1000-8000-00805f9b34fb"

# --- Printhead ---

PRINTHEAD_PX = 96
BYTES_PER_ROW = PRINTHEAD_PX // 8  # 12
CHUNK_SIZE_BLE = 200        # BLE MTU-limited
CHUNK_SIZE_CLASSIC = 16384  # from decompiled app (C1703d.java), stream-based

# --- Paper types for 10 FF 84 nn ---

PAPER_GAP = 0x00
PAPER_BLACK_MARK = 0x01
PAPER_CONTINUOUS = 0x02

# --- Timing (seconds) - empirically tuned against D11s fw 2.4.6 ---

DELAY_AFTER_DENSITY = 0.10   # printer needs time to apply density setting
DELAY_COMMAND_GAP = 0.05     # minimum gap between sequential commands
DELAY_CHUNK_GAP = 0.02       # inter-chunk pacing for BLE throughput
DELAY_RASTER_SETTLE = 0.50   # wait for printhead after raster transfer
DELAY_AFTER_FEED = 0.30      # wait after form feed before stop command
DELAY_NOTIFY_EXTRA = 0.05    # extra wait for trailing BLE notification fragments


# --- Exceptions ---


class PrinterError(Exception):
    """Base exception for printer operations."""


class PrinterNotFound(PrinterError):
    """No Fichero/D11s printer found during BLE scan."""


class PrinterTimeout(PrinterError):
    """Printer did not respond within the expected time."""


class PrinterNotReady(PrinterError):
    """Printer status indicates it cannot print."""


# --- Discovery ---


async def find_printer() -> str:
    """Scan BLE for a Fichero/D11s printer. Returns the address."""
    print("Scanning for printer...")
    devices = await BleakScanner.discover(timeout=8)
    for d in devices:
        if d.name and any(d.name.startswith(p) for p in PRINTER_NAME_PREFIXES):
            print(f"  Found {d.name} at {d.address}")
            return d.address
    raise PrinterNotFound("No Fichero/D11s printer found. Is it turned on?")


# --- BlueZ LE-only connect (Linux) ---
#
# The printer advertises over BLE without the "BR/EDR not supported" flag, so
# BlueZ treats it as dual-mode. Before 5.77 (no PreferredBearer), Device1.Connect
# brings up the LE link, then also tries BR/EDR profiles, fails with
# "br-connection-profile-unavailable" and tears the whole connection down.
# Adapter1.ConnectDevice connects over LE only, but it is an experimental API:
# bluetoothd needs "Experimental = true" in /etc/bluetooth/main.conf.

BLUEZ_BR_PROFILE_ERROR = "br-connection-profile-unavailable"


def _is_bluez_br_profile_error(exc: BaseException) -> bool:
    return (
        sys.platform == "linux"
        and isinstance(exc, BleakDBusError)
        and exc.dbus_error_details == BLUEZ_BR_PROFILE_ERROR
    )


@asynccontextmanager
async def _bluez_bus():
    """Yield a call(path, interface, member, signature, body) helper on the system bus."""
    from dbus_fast import BusType, Message, MessageType
    from dbus_fast.aio import MessageBus

    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()

    async def call(path, interface, member, signature="", body=()):
        reply = await bus.call(
            Message(
                destination="org.bluez",
                path=path,
                interface=interface,
                member=member,
                signature=signature,
                body=list(body),
            )
        )
        if reply.message_type == MessageType.ERROR:
            raise BleakDBusError(reply.error_name, reply.body)
        return reply.body

    try:
        yield call
    finally:
        bus.disconnect()


async def _bluez_connect_le(address: str) -> BLEDevice:
    """Open an LE-only link via Adapter1.ConnectDevice. Returns a BLEDevice for it."""
    from dbus_fast import Variant

    async with _bluez_bus() as call:
        (objects,) = await call("/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects")
        suffix = "/dev_" + address.upper().replace(":", "_")
        device_path = next((p for p in objects if p.endswith(suffix)), None)
        address_type = "public"

        if device_path is not None:
            props = objects[device_path]["org.bluez.Device1"]
            if props["Connected"].value:
                return BLEDevice(address, None, {"path": device_path, "props": {}})
            if props["Paired"].value:
                raise PrinterError(
                    f"{address} is paired as a dual-mode device; BlueZ keeps picking "
                    f"BR/EDR for it. Remove it (bluetoothctl remove {address}) and retry."
                )
            address_type = props["AddressType"].value
            adapter_path = device_path.rsplit("/", 1)[0]
            # ConnectDevice refuses addresses BlueZ already knows about. This
            # entry is an unpaired cache object, so dropping it loses nothing.
            await call(adapter_path, "org.bluez.Adapter1", "RemoveDevice", "o", [device_path])
        else:
            adapter_path = next(
                (p for p, ifaces in objects.items() if "org.bluez.Adapter1" in ifaces), None
            )
            if adapter_path is None:
                raise PrinterError("No Bluetooth adapter found")

        try:
            (device_path,) = await call(
                adapter_path,
                "org.bluez.Adapter1",
                "ConnectDevice",
                "a{sv}",
                [{"Address": Variant("s", address), "AddressType": Variant("s", address_type)}],
            )
        except BleakDBusError as e:
            if e.dbus_error == "org.freedesktop.DBus.Error.UnknownMethod":
                raise PrinterError(
                    "BlueZ tried to connect over Classic Bluetooth and failed. The LE-only "
                    "workaround needs bluetoothd's experimental API: set "
                    "'Experimental = true' under [General] in /etc/bluetooth/main.conf, "
                    "then run 'sudo systemctl restart bluetooth'."
                ) from e
            raise
        return BLEDevice(address, None, {"path": device_path, "props": {}})


def _find_connected_printer(objects: dict, address: str | None) -> tuple[str, str] | None:
    """Return (path, address) of a connected printer in a GetManagedObjects result.

    Without an address, matches on the name prefix: a connected printer stops
    advertising, so it cannot be found by scanning.
    """
    for path, ifaces in objects.items():
        props = ifaces.get("org.bluez.Device1")
        if not props or not props["Connected"].value:
            continue
        if address:
            if props["Address"].value.upper() != address.upper():
                continue
        else:
            name = props.get("Name")
            if not name or not name.value.startswith(PRINTER_NAME_PREFIXES):
                continue
        return path, props["Address"].value
    return None


async def _bluez_connected_printer(address: str | None = None) -> BLEDevice | None:
    """Return the printer if BlueZ already holds a link to it (e.g. from `fichero connect`)."""
    if sys.platform != "linux":
        return None
    try:
        async with _bluez_bus() as call:
            (objects,) = await call("/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects")
    except Exception:
        return None  # no system bus or no bluetoothd: fall back to scanning
    found = _find_connected_printer(objects, address)
    if found is None:
        return None
    path, addr = found
    return BLEDevice(addr, None, {"path": path, "props": {}})


async def bluez_disconnect(address: str | None = None) -> str:
    """Disconnect a printer link left up by `fichero connect`. Returns its address."""
    async with _bluez_bus() as call:
        (objects,) = await call("/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects")
        found = _find_connected_printer(objects, address)
        if found is not None:
            path, addr = found
            await call(path, "org.bluez.Device1", "Disconnect")
            return addr
    raise PrinterNotFound(f"No connected printer{' at ' + address if address else ''} found")


# --- Status ---


class PrinterStatus:
    """Parsed status byte from 10 FF 40."""

    def __init__(self, byte: int):
        self.raw = byte
        self.printing = bool(byte & 0x01)
        self.cover_open = bool(byte & 0x02)
        self.no_paper = bool(byte & 0x04)
        self.low_battery = bool(byte & 0x08)
        self.overheated = bool(byte & 0x10 or byte & 0x40)
        self.charging = bool(byte & 0x20)

    def __str__(self) -> str:
        flags = []
        if self.printing:
            flags.append("printing")
        if self.cover_open:
            flags.append("cover open")
        if self.no_paper:
            flags.append("no paper")
        if self.low_battery:
            flags.append("low battery")
        if self.overheated:
            flags.append("overheated")
        if self.charging:
            flags.append("charging")
        return ", ".join(flags) if flags else "ready"

    @property
    def ok(self) -> bool:
        return not (self.cover_open or self.no_paper or self.overheated)


# --- RFCOMM client (duck-types the BleakClient interface) ---


class RFCOMMClient:
    """Classic Bluetooth (RFCOMM) transport. Linux + Windows (Python 3.9+).

    Implements the same async context manager + write_gatt_char/start_notify
    interface that PrinterClient expects from BleakClient.  Zero dependencies
    beyond stdlib.
    """

    is_classic = True  # transport marker for PrinterClient chunk sizing

    def __init__(self, address: str, channel: int = RFCOMM_CHANNEL):
        self._address = address
        self._channel = channel
        self._sock: "_socket.socket | None" = None
        self._reader_task: asyncio.Task | None = None

    async def __aenter__(self) -> "RFCOMMClient":
        if not _RFCOMM_AVAILABLE:
            raise PrinterError(
                "RFCOMM transport requires socket.AF_BLUETOOTH "
                "(Linux with BlueZ, or Windows with Python 3.9+). "
                "Not available on this platform."
            )
        import socket as _socket

        sock = _socket.socket(
            _socket.AF_BLUETOOTH, _socket.SOCK_STREAM, _socket.BTPROTO_RFCOMM
        )
        sock.setblocking(False)
        loop = asyncio.get_running_loop()
        try:
            await asyncio.wait_for(
                loop.sock_connect(sock, (self._address, self._channel)),
                timeout=10.0,
            )
        except Exception:
            sock.close()
            raise
        self._sock = sock
        return self

    async def __aexit__(self, *exc) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    async def write_gatt_char(self, _uuid: str, data: bytes, response: bool = False) -> None:
        loop = asyncio.get_running_loop()
        await loop.sock_sendall(self._sock, data)

    async def start_notify(self, _uuid: str, callback) -> None:
        self._reader_task = asyncio.create_task(self._reader_loop(callback))

    async def _reader_loop(self, callback) -> None:
        loop = asyncio.get_running_loop()
        while True:
            try:
                data = await loop.sock_recv(self._sock, 1024)
            except (OSError, asyncio.CancelledError):
                return
            if not data:
                return
            callback(None, bytearray(data))


# --- Client ---


class PrinterClient:
    def __init__(self, client: BleakClient):
        self.client = client
        self._buf = bytearray()
        self._event = asyncio.Event()
        self._lock = asyncio.Lock()
        self._is_classic = getattr(client, "is_classic", False)

    def _on_notify(self, _char: BleakGATTCharacteristic, data: bytearray) -> None:
        self._buf.extend(data)
        self._event.set()

    async def start(self) -> None:
        await self.client.start_notify(NOTIFY_UUID, self._on_notify)

    async def send(self, data: bytes, wait: bool = False, timeout: float = 2.0) -> bytes:
        async with self._lock:
            if wait:
                self._buf.clear()
                self._event.clear()
            await self.client.write_gatt_char(WRITE_UUID, data, response=False)
            if wait:
                try:
                    await asyncio.wait_for(self._event.wait(), timeout=timeout)
                    await asyncio.sleep(DELAY_NOTIFY_EXTRA)
                except asyncio.TimeoutError:
                    raise PrinterTimeout(f"No response within {timeout}s")
            return bytes(self._buf)

    async def send_chunked(self, data: bytes, chunk_size: int | None = None) -> None:
        if chunk_size is None:
            chunk_size = CHUNK_SIZE_CLASSIC if self._is_classic else CHUNK_SIZE_BLE
        delay = 0 if self._is_classic else DELAY_CHUNK_GAP
        async with self._lock:
            for i in range(0, len(data), chunk_size):
                chunk = data[i : i + chunk_size]
                await self.client.write_gatt_char(WRITE_UUID, chunk, response=False)
                if delay:
                    await asyncio.sleep(delay)

    # --- Info commands (all tested and confirmed on D11s fw 2.4.6) ---

    async def get_model(self) -> str:
        r = await self.send(bytes([0x10, 0xFF, 0x20, 0xF0]), wait=True)
        return r.decode(errors="replace").strip() if r else "?"

    async def get_firmware(self) -> str:
        r = await self.send(bytes([0x10, 0xFF, 0x20, 0xF1]), wait=True)
        return r.decode(errors="replace").strip() if r else "?"

    async def get_serial(self) -> str:
        r = await self.send(bytes([0x10, 0xFF, 0x20, 0xF2]), wait=True)
        return r.decode(errors="replace").strip() if r else "?"

    async def get_boot_version(self) -> str:
        r = await self.send(bytes([0x10, 0xFF, 0x20, 0xEF]), wait=True)
        return r.decode(errors="replace").strip() if r else "?"

    async def get_battery(self) -> int:
        r = await self.send(bytes([0x10, 0xFF, 0x50, 0xF1]), wait=True)
        if r and len(r) >= 2:
            return r[-1]
        return -1

    async def get_status(self) -> PrinterStatus:
        r = await self.send(bytes([0x10, 0xFF, 0x40]), wait=True)
        if r:
            return PrinterStatus(r[-1])
        return PrinterStatus(0xFF)

    async def get_density(self) -> bytes:
        r = await self.send(bytes([0x10, 0xFF, 0x11]), wait=True)
        return r

    async def get_shutdown_time(self) -> int:
        """Returns auto-shutdown timeout in minutes."""
        r = await self.send(bytes([0x10, 0xFF, 0x13]), wait=True)
        if r and len(r) >= 2:
            return (r[0] << 8) | r[1]
        return -1

    async def get_all_info(self) -> dict:
        """10 FF 70: returns pipe-delimited string with all device info."""
        r = await self.send(bytes([0x10, 0xFF, 0x70]), wait=True)
        if not r:
            return {}
        parts = r.decode(errors="replace").split("|")
        if len(parts) >= 6:
            return {
                "bt_name": parts[0],
                "mac_classic": parts[1],
                "mac_ble": parts[2],
                "firmware": parts[3],
                "serial": parts[4],
                "battery": f"{parts[5]}%",
            }
        return {"raw": r.decode(errors="replace")}

    # --- Config commands (tested on D11s) ---

    async def set_density(self, level: int) -> bool:
        """0=light, 1=medium, 2=thick. Returns True if printer responded OK."""
        r = await self.send(bytes([0x10, 0xFF, 0x10, 0x00, level]), wait=True)
        return r == b"OK"

    async def set_paper_type(self, paper: int = PAPER_GAP) -> bool:
        """0=gap/label, 1=black mark, 2=continuous."""
        r = await self.send(bytes([0x10, 0xFF, 0x84, paper]), wait=True)
        return r == b"OK"

    async def set_shutdown_time(self, minutes: int) -> bool:
        hi = (minutes >> 8) & 0xFF
        lo = minutes & 0xFF
        r = await self.send(bytes([0x10, 0xFF, 0x12, hi, lo]), wait=True)
        return r == b"OK"

    async def factory_reset(self) -> bool:
        r = await self.send(bytes([0x10, 0xFF, 0x04]), wait=True)
        return r == b"OK"

    # --- Print control (AiYin-specific, from decompiled APK) ---

    async def wakeup(self) -> None:
        await self.send(b"\x00" * 12)

    async def enable(self) -> None:
        """AiYin enable: 10 FF FE 01 (NOT 10 FF F1 03)."""
        await self.send(bytes([0x10, 0xFF, 0xFE, 0x01]))

    async def feed_dots(self, dots: int) -> None:
        """Feed paper forward by n dots."""
        await self.send(bytes([0x1B, 0x4A, dots & 0xFF]))

    async def form_feed(self) -> None:
        """Position to next label."""
        await self.send(bytes([0x1D, 0x0C]))

    async def stop_print(self) -> bool:
        """AiYin stop: 10 FF FE 45. Waits for 0xAA or 'OK'."""
        r = await self.send(bytes([0x10, 0xFF, 0xFE, 0x45]), wait=True, timeout=60.0)
        if r:
            return r[0] == 0xAA or r.startswith(b"OK")
        return False

    async def get_info(self) -> dict:
        status = await self.get_status()
        return {
            "model": await self.get_model(),
            "firmware": await self.get_firmware(),
            "boot": await self.get_boot_version(),
            "serial": await self.get_serial(),
            "battery": f"{await self.get_battery()}%",
            "status": str(status),
            "shutdown": f"{await self.get_shutdown_time()} min",
        }


@asynccontextmanager
async def connect(
    address: str | None = None,
    classic: bool = False,
    channel: int = RFCOMM_CHANNEL,
) -> AsyncGenerator[PrinterClient, None]:
    """Discover printer, connect, and yield a ready PrinterClient."""
    if classic:
        if not address:
            raise PrinterError("--address is required for Classic Bluetooth (no scanning)")
        async with RFCOMMClient(address, channel) as client:
            pc = PrinterClient(client)
            await pc.start()
            yield pc
    else:
        # A connected printer stops advertising, so scanning would miss it.
        existing = await _bluez_connected_printer(address)
        addr = existing or address or await find_printer()
        try:
            async with AsyncExitStack() as stack:
                try:
                    client = await stack.enter_async_context(BleakClient(addr))
                except BleakDBusError as e:
                    if not _is_bluez_br_profile_error(e):
                        raise
                    print("BlueZ picked Classic Bluetooth, retrying over LE only...")
                    client = await stack.enter_async_context(
                        BleakClient(await _bluez_connect_le(addr))
                    )
                pc = PrinterClient(client)
                await pc.start()
                yield pc
        finally:
            if existing is not None:
                # Bleak always disconnects on exit, which drops the link for every
                # BlueZ client. Reopen the link that `fichero connect` left up.
                try:
                    await _bluez_connect_le(existing.address)
                except Exception as e:
                    print(f"  WARNING: could not reopen the LE link: {e}")
