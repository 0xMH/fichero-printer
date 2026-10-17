"""BLE discovery and protocol tests using notifications, without a radio."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from PIL import Image

from fichero import (
    PrinterNotFound,
    PrinterNotReady,
    PrinterTimeout,
    RFCOMMClient,
    USBClient,
    connect,
)
from fichero.cli import do_print
from fichero.printer import NOTIFY_UUID, WRITE_UUID, PrinterClient, find_printer


class FakeBLE:
    """Emulate only the established Bluetooth replies used by these tests."""

    is_classic = False

    def __init__(self, status=0):
        self.status = status
        self.writes = []
        self.closed = False
        self.callback = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        self.closed = True

    async def start_notify(self, uuid, callback):
        assert uuid == NOTIFY_UUID
        self.callback = callback

    async def write_gatt_char(self, uuid, data, response=False):
        assert uuid == WRITE_UUID and response is False
        self.writes.append(bytes(data))
        replies = {
            bytes.fromhex("10 ff 40"): bytes([self.status]),
            bytes.fromhex("10 ff 20 f0"): b"D11s",
            bytes.fromhex("10 ff 10 00 02"): b"OK",
            bytes.fromhex("10 ff 84 00"): b"OK",
            bytes.fromhex("10 ff fe 45"): b"\xaa",
        }
        if data in replies:
            self.callback(None, bytearray(replies[data]))


@pytest.mark.asyncio
async def test_discovery_and_connection():
    device = FakeBLE()
    discovered = [
        SimpleNamespace(name=None, address="ignored"),
        SimpleNamespace(name="Headphones", address="ignored"),
        SimpleNamespace(name="D11s_TEST", address="test-address"),
    ]
    with (
        patch(
            "fichero.printer.BleakScanner.discover", AsyncMock(return_value=discovered)
        ) as scan,
        patch("fichero.printer.BleakClient", return_value=device) as client,
    ):
        async with connect() as printer:
            assert await printer.get_model() == "D11s"
        scan.assert_awaited_once_with(timeout=8)
        client.assert_called_once_with("test-address")
    assert device.closed


@pytest.mark.asyncio
async def test_missing_printer():
    with patch("fichero.printer.BleakScanner.discover", AsyncMock(return_value=[])):
        with pytest.raises(PrinterNotFound):
            await find_printer()


@pytest.mark.asyncio
async def test_print_sequence_and_acknowledgments():
    device = FakeBLE()
    with patch("fichero.printer.BleakClient", return_value=device):
        async with connect("test-address") as printer:
            assert await do_print(printer, Image.new("1", (96, 30), 0), density=2)
    raster = bytes.fromhex("1d 76 30 00 0c 00 1e 00") + b"\xff" * 360
    assert device.writes == [
        bytes.fromhex("10 ff 10 00 02"),
        bytes.fromhex("10 ff 40"),
        bytes.fromhex("10 ff 84 00"),
        b"\0" * 12,
        bytes.fromhex("10 ff fe 01"),
        raster[:200],
        raster[200:],
        bytes.fromhex("1d 0c"),
        bytes.fromhex("10 ff fe 45"),
    ]
    assert device.closed


@pytest.mark.asyncio
async def test_cover_open_prevents_raster_and_closes_connection():
    device = FakeBLE(status=0x02)
    with patch("fichero.printer.BleakClient", return_value=device):
        with pytest.raises(PrinterNotReady, match="cover open"):
            async with connect("test-address") as printer:
                await do_print(printer, Image.new("1", (96, 30), 0), density=2)
    assert device.writes == [bytes.fromhex("10 ff 10 00 02"), bytes.fromhex("10 ff 40")]
    assert device.closed


@pytest.mark.asyncio
async def test_missing_notification_times_out():
    device = FakeBLE()
    printer = PrinterClient(device)
    await printer.start()
    with pytest.raises(PrinterTimeout, match="No response"):
        await printer.send(b"unanswered", wait=True, timeout=0.01)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "transport,size,delays",
    [
        (lambda: SimpleNamespace(), 200, [0.02, 0.02]),
        (lambda: RFCOMMClient("AA:BB:CC:DD:EE:FF"), 16384, []),
        (lambda: USBClient(), 256, [0.02, 0.02]),
    ],
)
async def test_transport_chunk_pacing(transport, size, delays):
    client = transport()
    client.write_gatt_char = AsyncMock()
    pc = PrinterClient(client)
    with patch("fichero.printer.asyncio.sleep", new_callable=AsyncMock) as sleep:
        await pc.send_chunked(b"x" * (size + 1))
    assert [len(c.args[1]) for c in client.write_gatt_char.call_args_list] == [size, 1]
    assert [c.args[0] for c in sleep.await_args_list] == delays


@pytest.mark.asyncio
@pytest.mark.parametrize("classic", [False, True])
async def test_bluetooth_reply_semantics(classic):
    client = SimpleNamespace(is_classic=classic, write_gatt_char=AsyncMock())
    pc = PrinterClient(client)

    async def reply(*args, **kwargs):
        pc._on_notify(None, bytearray(b"OK"))

    client.write_gatt_char.side_effect = reply
    assert await pc.set_density(2) is True
    assert await pc.set_paper_type(0) is True
    assert await pc.stop_print() is True
