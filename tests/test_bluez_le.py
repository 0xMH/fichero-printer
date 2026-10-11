"""Tests for the BlueZ LE-only connect fallback."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bleak.exc import BleakDBusError

from fichero.printer import PrinterClient, _is_bluez_br_profile_error, connect

ADDR = "AA:BB:CC:DD:EE:FF"
BR_ERROR = BleakDBusError("org.bluez.Error.NotAvailable", ["br-connection-profile-unavailable"])


def _mock_bleak(enter_side_effect=None):
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client, side_effect=enter_side_effect)
    client.__aexit__ = AsyncMock(return_value=None)
    client.start_notify = AsyncMock()
    return client


class TestIsBlueZBrProfileError:
    def test_matches_on_linux(self):
        with patch("fichero.printer.sys.platform", "linux"):
            assert _is_bluez_br_profile_error(BR_ERROR)

    def test_ignored_off_linux(self):
        with patch("fichero.printer.sys.platform", "darwin"):
            assert not _is_bluez_br_profile_error(BR_ERROR)

    def test_other_dbus_errors_ignored(self):
        err = BleakDBusError("org.bluez.Error.Failed", ["le-connection-abort-by-local"])
        with patch("fichero.printer.sys.platform", "linux"):
            assert not _is_bluez_br_profile_error(err)


class TestConnectFallback:
    @pytest.mark.asyncio
    async def test_retries_over_le_on_br_profile_error(self):
        failing = _mock_bleak(enter_side_effect=BR_ERROR)
        working = _mock_bleak()
        le_device = MagicMock()

        with (
            patch("fichero.printer.sys.platform", "linux"),
            patch("fichero.printer.BleakClient", side_effect=[failing, working]) as mock_cls,
            patch("fichero.printer._bluez_connect_le", AsyncMock(return_value=le_device)) as mock_le,
        ):
            async with connect(ADDR) as pc:
                assert isinstance(pc, PrinterClient)
                assert pc.client is working

        mock_le.assert_awaited_once_with(ADDR)
        assert mock_cls.call_args_list[1].args == (le_device,)
        working.__aexit__.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_other_errors_propagate_without_fallback(self):
        err = BleakDBusError("org.bluez.Error.Failed", ["le-connection-abort-by-local"])
        failing = _mock_bleak(enter_side_effect=err)

        with (
            patch("fichero.printer.sys.platform", "linux"),
            patch("fichero.printer.BleakClient", return_value=failing),
            patch("fichero.printer._bluez_connect_le", AsyncMock()) as mock_le,
        ):
            with pytest.raises(BleakDBusError):
                async with connect(ADDR):
                    pass

        mock_le.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_body_errors_are_not_retried(self):
        """A BR-profile error raised by the caller's code must not trigger a reconnect."""
        working = _mock_bleak()

        with (
            patch("fichero.printer.sys.platform", "linux"),
            patch("fichero.printer.BleakClient", return_value=working),
            patch("fichero.printer._bluez_connect_le", AsyncMock()) as mock_le,
        ):
            with pytest.raises(BleakDBusError):
                async with connect(ADDR):
                    raise BR_ERROR

        mock_le.assert_not_awaited()
        working.__aexit__.assert_awaited_once()


class TestBlueZDisconnect:
    @staticmethod
    def _bus(objects):
        from contextlib import asynccontextmanager

        call = AsyncMock(side_effect=lambda path, iface, member, *a: (
            [objects] if member == "GetManagedObjects" else []
        ))

        @asynccontextmanager
        async def bus():
            yield call

        return bus, call

    @staticmethod
    def _dev(address, name, connected=True):
        from dbus_fast import Variant

        return {"org.bluez.Device1": {
            "Address": Variant("s", address),
            "Name": Variant("s", name),
            "Connected": Variant("b", connected),
        }}

    @pytest.mark.asyncio
    async def test_picks_connected_printer_by_name(self):
        from fichero.printer import bluez_disconnect

        objects = {
            "/org/bluez/hci0/dev_11": self._dev("11:11:11:11:11:11", "MX Vertical"),
            "/org/bluez/hci0/dev_22": self._dev("22:22:22:22:22:22", "FICHERO_5836_BLE"),
        }
        bus, call = self._bus(objects)
        with patch("fichero.printer._bluez_bus", bus):
            assert await bluez_disconnect() == "22:22:22:22:22:22"
        call.assert_any_await("/org/bluez/hci0/dev_22", "org.bluez.Device1", "Disconnect")
        assert not any(c.args[0] == "/org/bluez/hci0/dev_11" for c in call.await_args_list)

    @pytest.mark.asyncio
    async def test_raises_when_nothing_connected(self):
        from fichero.printer import PrinterNotFound, bluez_disconnect

        objects = {"/org/bluez/hci0/dev_22": self._dev("22:22:22:22:22:22", "FICHERO", False)}
        bus, _ = self._bus(objects)
        with patch("fichero.printer._bluez_bus", bus):
            with pytest.raises(PrinterNotFound):
                await bluez_disconnect()


class TestReuseConnectedLink:
    @pytest.mark.asyncio
    async def test_connect_reuses_existing_link_and_reopens_it(self):
        le_device = MagicMock(address=ADDR)
        client = _mock_bleak()

        with (
            patch("fichero.printer._bluez_connected_printer", AsyncMock(return_value=le_device)),
            patch("fichero.printer.find_printer", AsyncMock()) as mock_find,
            patch("fichero.printer.BleakClient", return_value=client) as mock_cls,
            patch("fichero.printer._bluez_connect_le", AsyncMock()) as mock_le,
        ):
            async with connect() as pc:
                assert pc.client is client
                mock_le.assert_not_awaited()

        mock_find.assert_not_awaited()
        mock_cls.assert_called_once_with(le_device)
        mock_le.assert_awaited_once_with(ADDR)

    @pytest.mark.asyncio
    async def test_fresh_link_is_not_reopened(self):
        client = _mock_bleak()

        with (
            patch("fichero.printer.BleakClient", return_value=client),
            patch("fichero.printer._bluez_connect_le", AsyncMock()) as mock_le,
        ):
            async with connect(ADDR):
                pass

        mock_le.assert_not_awaited()

    def test_find_connected_printer_matches_address_case_insensitively(self):
        from fichero.printer import _find_connected_printer

        objects = {
            "/org/bluez/hci0/dev_22": TestBlueZDisconnect._dev("22:99:17:B1:F9:6F", "FICHERO_5836_BLE"),
        }
        assert _find_connected_printer(objects, "22:99:17:b1:f9:6f") == (
            "/org/bluez/hci0/dev_22", "22:99:17:B1:F9:6F",
        )
        assert _find_connected_printer(objects, "11:11:11:11:11:11") is None
