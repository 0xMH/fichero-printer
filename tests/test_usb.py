"""USB lifecycle and wire-level regression tests; no printer required."""

import asyncio
import errno
import queue
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("usb", reason="requires the usb extra")

import usb.core  # noqa: E402
from PIL import Image

from fichero import (
    PrinterError,
    PrinterNotFound,
    PrinterNotReady,
    PrinterTimeout,
    USBClient,
    connect,
    discover_usb,
)
from fichero.cli import do_print


@pytest.fixture
def hardware():
    endpoints = [SimpleNamespace(bmAttributes=2, bEndpointAddress=a) for a in (1, 129)]

    class Interface(list):
        bInterfaceClass = 7
        bInterfaceSubClass = 1
        bInterfaceProtocol = 2
        bAlternateSetting = 0
        bInterfaceNumber = 0

    device = MagicMock()
    device.serial_number = "example"
    device.bus, device.address = 1, 2
    device.get_active_configuration.return_value = [Interface(endpoints)]
    device.is_kernel_driver_active.return_value = True
    # Replies observed on a D11s (fw 2.4.9) over bulk IN; unread ones persist.
    device.replies = {
        bytes.fromhex("10 ff 40"): b"\x00",
        bytes.fromhex("10 ff 20 f0"): b"D11s",
        bytes.fromhex("10 ff 10 00 02"): b"OK",
        bytes.fromhex("10 ff 84 00"): b"OK",
        bytes.fromhex("10 ff fe 45"): b"OK",
    }
    device.pending = queue.Queue()

    def write(ep, data, timeout):
        reply = device.replies.get(bytes(data))
        if reply is not None:
            device.pending.put(reply)
        return len(data)

    def read(ep, size, timeout):
        assert ep == 129
        try:
            return device.pending.get(timeout=timeout / 1000)
        except queue.Empty:
            raise usb.core.USBTimeoutError("timeout") from None

    device.write.side_effect = write
    device.read.side_effect = read
    util = MagicMock()
    core = MagicMock(
        USBError=usb.core.USBError,
        USBTimeoutError=usb.core.USBTimeoutError,
        NoBackendError=usb.core.NoBackendError,
    )
    core.find.return_value = [device]
    with patch("fichero.usb._modules", return_value=(core, util)):
        yield device, core, util


@pytest.mark.asyncio
async def test_discovery(hardware):
    device, core, util = hardware
    assert await discover_usb() == [{"serial": "example", "bus": 1, "address": 2}]
    core.find.assert_called_once_with(find_all=True, idVendor=0x09C5, idProduct=0x0200)
    util.claim_interface.assert_not_called()
    util.dispose_resources.assert_called_once_with(device)


@pytest.mark.asyncio
@pytest.mark.parametrize("devices,message", [(0, "No matching"), (2, "Multiple")])
async def test_selection(hardware, devices, message):
    device, core, util = hardware
    core.find.return_value = [device] * devices
    with pytest.raises(PrinterError, match=message):
        async with USBClient():
            pass
    util.claim_interface.assert_not_called()


@pytest.mark.asyncio
async def test_serial_selector(hardware):
    with pytest.raises(PrinterNotFound):
        async with USBClient(serial="other"):
            pass
    async with USBClient(serial="example"):
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "number,message", [(errno.EACCES, "permission denied"), (errno.EBUSY, "busy")]
)
async def test_claim_failure_restores_driver(hardware, number, message):
    device, _, util = hardware
    util.claim_interface.side_effect = usb.core.USBError("failure", errno=number)
    with pytest.raises(PrinterError, match=message):
        async with USBClient():
            pass
    device.detach_kernel_driver.assert_called_once_with(0)
    device.attach_kernel_driver.assert_called_once_with(0)
    util.dispose_resources.assert_called_once_with(device)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure,exception",
    [
        (0, PrinterError),
        (usb.core.USBTimeoutError("timeout"), PrinterTimeout),
        (usb.core.USBError("disconnected"), PrinterError),
    ],
)
async def test_write_failure_cleanup(hardware, failure, exception):
    device, _, util = hardware
    device.write.side_effect = failure if isinstance(failure, Exception) else None
    device.write.return_value = failure
    with pytest.raises(exception):
        async with USBClient() as client:
            await client.write_gatt_char("", b"abc")
    util.release_interface.assert_called_once_with(device, 0)
    device.attach_kernel_driver.assert_called_once_with(0)
    util.dispose_resources.assert_called_once_with(device)


@pytest.mark.asyncio
async def test_timeout_errno_maps_to_printer_timeout(hardware):
    device, _, _ = hardware
    device.write.side_effect = usb.core.USBError("timeout", errno=errno.ETIMEDOUT)
    with pytest.raises(PrinterTimeout, match="outcome is unknown"):
        async with USBClient() as client:
            await client.write_gatt_char("", b"abc")


@pytest.mark.asyncio
async def test_no_kernel_driver(hardware):
    device, _, util = hardware
    device.is_kernel_driver_active.side_effect = NotImplementedError
    async with USBClient():
        pass
    device.detach_kernel_driver.assert_not_called()
    device.attach_kernel_driver.assert_not_called()
    util.release_interface.assert_called_once()


@pytest.mark.asyncio
async def test_bad_endpoints(hardware):
    device, _, util = hardware
    device.get_active_configuration.return_value = []
    with pytest.raises(PrinterError, match="interface"):
        async with USBClient():
            pass
    util.dispose_resources.assert_called_once_with(device)


@pytest.mark.asyncio
async def test_missing_backend(hardware):
    _, core, _ = hardware
    core.find.side_effect = usb.core.NoBackendError("No backend")
    with pytest.raises(PrinterError, match="install libusb"):
        await discover_usb()


@pytest.mark.asyncio
async def test_missing_pyusb():
    with (
        patch.dict("sys.modules", {"usb.core": None}),
        pytest.raises(PrinterError, match="extra usb"),
    ):
        await discover_usb()


@pytest.mark.asyncio
async def test_print_wire_sequence(hardware, capsys):
    device, _, _ = hardware

    # Literal all-black raster makes orientation/packing independent of mocks.
    async def no_delay(_):
        pass

    with patch("fichero.cli.asyncio.sleep", no_delay):
        async with connect(usb=True) as pc:
            assert await do_print(pc, Image.new("1", (96, 30), 0), density=2, copies=2)
            assert await pc.get_model() == "D11s"
    raster = bytes.fromhex("1d 76 30 00 0c 00 1e 00") + b"\xff" * 360
    copy = [
        bytes.fromhex("10 ff 40"),
        bytes.fromhex("10 ff 84 00"),
        b"\0" * 12,
        bytes.fromhex("10 ff fe 01"),
        raster[:256],
        raster[256:],
        bytes.fromhex("1d 0c"),
        bytes.fromhex("10 ff fe 45"),
    ]
    assert [call.args[1] for call in device.write.call_args_list] == [
        bytes.fromhex("10 ff 10 00 02")
    ] + copy * 2 + [bytes.fromhex("10 ff 20 f0")]
    assert all(
        call.args[0] == 1 and call.kwargs == {"timeout": 5000}
        for call in device.write.call_args_list
    )
    assert "WARNING" not in capsys.readouterr().out


@pytest.mark.asyncio
async def test_cancelled_open_cleans_after_worker(hardware):
    device, _, util = hardware
    started, finish = threading.Event(), threading.Event()

    def claim(*_):
        started.set()
        assert finish.wait(3)

    util.claim_interface.side_effect = claim

    async def run():
        async with USBClient():
            pass

    task = asyncio.create_task(run())
    await asyncio.to_thread(started.wait, 3)
    task.cancel()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    util.release_interface.assert_called_once_with(device, 0)
    device.attach_kernel_driver.assert_called_once()


@pytest.mark.asyncio
async def test_descriptor_permission_diagnostic(hardware):
    device, _, util = hardware
    from unittest.mock import PropertyMock

    type(device).serial_number = PropertyMock(side_effect=ValueError("no langid"))
    with pytest.raises(PrinterError, match="udev permissions"):
        await discover_usb()
    util.dispose_resources.assert_called_once_with(device)


@pytest.mark.asyncio
async def test_release_failure_still_restores_and_disposes(hardware):
    device, _, util = hardware
    util.release_interface.side_effect = usb.core.USBError("release failed")
    with pytest.raises(PrinterError, match="release failed"):
        async with USBClient():
            pass
    device.attach_kernel_driver.assert_called_once_with(0)
    util.dispose_resources.assert_called_once_with(device)


@pytest.mark.asyncio
async def test_cancelled_write_finishes_before_release(hardware):
    device, _, util = hardware
    started, finish = threading.Event(), threading.Event()
    events = []

    def write(ep, data, timeout):
        started.set()
        assert finish.wait(3)
        events.append("write completed")
        return len(data)

    device.write.side_effect = write
    util.release_interface.side_effect = lambda *_: events.append("released")

    async def run():
        async with USBClient() as client:
            await client.write_gatt_char("", b"hello")

    task = asyncio.create_task(run())
    assert await asyncio.to_thread(started.wait, 3)
    # Reaching here while write is blocked proves the event loop is responsive.
    task.cancel()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert events == ["write completed", "released"]


@pytest.mark.asyncio
async def test_cancelled_write_failure_still_raises_cancelled(hardware):
    device, _, util = hardware
    started, finish = threading.Event(), threading.Event()

    def write(ep, data, timeout):
        started.set()
        assert finish.wait(3)
        raise usb.core.USBError("disconnected")

    device.write.side_effect = write

    async def run():
        async with USBClient() as client:
            await client.write_gatt_char("", b"hello")

    task = asyncio.create_task(run())
    assert await asyncio.to_thread(started.wait, 3)
    task.cancel()
    finish.set()
    # The worker's PrinterError must not replace the cancellation.
    with pytest.raises(asyncio.CancelledError):
        await task
    util.release_interface.assert_called_once_with(device, 0)


@pytest.mark.asyncio
async def test_repeated_cancel_waits_for_write_before_release(hardware):
    device, _, util = hardware
    started, finish = threading.Event(), threading.Event()
    events = []

    def write(ep, data, timeout):
        started.set()
        assert finish.wait(3)
        events.append("write completed")
        return len(data)

    device.write.side_effect = write
    util.release_interface.side_effect = lambda *_: events.append("released")

    async def run():
        async with USBClient() as client:
            await client.write_gatt_char("", b"hello")

    task = asyncio.create_task(run())
    assert await asyncio.to_thread(started.wait, 3)
    task.cancel()
    await asyncio.sleep(0.05)  # deliver the first cancellation
    task.cancel()
    asyncio.get_running_loop().call_later(0.2, finish.set)
    with pytest.raises(asyncio.CancelledError):
        await task
    assert events == ["write completed", "released"]


@pytest.mark.asyncio
async def test_setters_report_usb_acknowledgments(hardware):
    device, _, _ = hardware
    async with connect(usb=True) as pc:
        assert await pc.set_density(2) is True
        assert await pc.set_paper_type(0) is True
        assert await pc.stop_print() is True
        device.replies[bytes.fromhex("10 ff 10 00 02")] = b"ER"
        assert await pc.set_density(2) is False


@pytest.mark.asyncio
async def test_stale_replies_are_drained_on_open(hardware):
    device, _, _ = hardware
    device.pending.put(b"OKOK")  # left unread by an earlier session
    async with connect(usb=True) as pc:
        assert await pc.get_model() == "D11s"


@pytest.mark.asyncio
async def test_split_reply_is_reassembled(hardware):
    device, _, _ = hardware
    def write(ep, data, timeout):
        if bytes(data) == bytes.fromhex("10 ff 70"):
            device.pending.put(b"FICHERO_5836|11:99|22:99|2.4.9|D263")
            device.pending.put(b"W1826|100")
        return len(data)

    device.write.side_effect = write
    async with connect(usb=True) as pc:
        info = await pc.get_all_info()
    assert info["serial"] == "D263W1826" and info["battery"] == "100%"


@pytest.mark.asyncio
async def test_cover_open_prevents_raster(hardware):
    device, _, _ = hardware
    device.replies[bytes.fromhex("10 ff 40")] = b"\x06"
    with pytest.raises(PrinterNotReady, match="cover open, no paper"):
        async with connect(usb=True) as pc:
            await do_print(pc, Image.new("1", (96, 30), 0), density=2)
    assert [call.args[1] for call in device.write.call_args_list] == [
        bytes.fromhex("10 ff 10 00 02"),
        bytes.fromhex("10 ff 40"),
    ]


@pytest.mark.asyncio
async def test_reader_stops_before_release(hardware):
    _, _, util = hardware
    alive = []
    util.release_interface.side_effect = lambda *_: alive.append(
        any(t.name == "fichero-usb-reader" for t in threading.enumerate())
    )
    async with connect(usb=True):
        assert any(t.name == "fichero-usb-reader" for t in threading.enumerate())
    assert alive == [False]


@pytest.mark.asyncio
async def test_disconnect_stops_reader_and_times_out(hardware):
    device, _, _ = hardware

    def read(ep, size, timeout):
        raise usb.core.USBError("No such device", errno=errno.ENODEV)

    async with connect(usb=True) as pc:
        device.read.side_effect = read
        for _ in range(50):
            if not pc.client._reader.is_alive():
                break
            await asyncio.sleep(0.02)
        assert not pc.client._reader.is_alive()
        with pytest.raises(PrinterTimeout):
            await pc.send(bytes.fromhex("10 ff 40"), wait=True, timeout=0.3)
