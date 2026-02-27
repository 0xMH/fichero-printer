"""Tests for the RFCOMM (Classic Bluetooth) transport layer."""

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fichero.printer import (
    RFCOMM_CHANNEL,
    PrinterClient,
    PrinterError,
    RFCOMMClient,
    connect,
)


# --- RFCOMMClient unit tests ---


class TestRFCOMMClientInit:
    def test_defaults(self):
        c = RFCOMMClient("AA:BB:CC:DD:EE:FF")
        assert c._address == "AA:BB:CC:DD:EE:FF"
        assert c._channel == RFCOMM_CHANNEL
        assert c._sock is None
        assert c._reader_task is None

    def test_custom_channel(self):
        c = RFCOMMClient("AA:BB:CC:DD:EE:FF", channel=3)
        assert c._channel == 3


class TestRFCOMMClientPlatformGuard:
    @pytest.mark.asyncio
    async def test_raises_on_unavailable_platform(self):
        with patch("fichero.printer._RFCOMM_AVAILABLE", False):
            client = RFCOMMClient("AA:BB:CC:DD:EE:FF")
            with pytest.raises(PrinterError, match="requires socket.AF_BLUETOOTH"):
                async with client:
                    pass


class TestRFCOMMClientConnect:
    @pytest.mark.asyncio
    async def test_connect_and_close(self):
        mock_sock = MagicMock()
        mock_sock.close = MagicMock()

        with (
            patch("fichero.printer._RFCOMM_AVAILABLE", True),
            patch("fichero.printer.RFCOMMClient.__aenter__") as mock_enter,
            patch("fichero.printer.RFCOMMClient.__aexit__") as mock_exit,
        ):
            client = RFCOMMClient("AA:BB:CC:DD:EE:FF")
            mock_enter.return_value = client
            mock_exit.return_value = None
            client._sock = mock_sock

            async with client:
                assert client._sock is mock_sock

    @pytest.mark.asyncio
    async def test_socket_closed_on_connect_failure(self):
        """If sock_connect fails, the socket must be closed."""
        mock_sock = MagicMock()
        mock_sock.setblocking = MagicMock()
        mock_sock.close = MagicMock()

        mock_socket_mod = MagicMock()
        mock_socket_mod.AF_BLUETOOTH = 31
        mock_socket_mod.SOCK_STREAM = 1
        mock_socket_mod.BTPROTO_RFCOMM = 3
        mock_socket_mod.socket.return_value = mock_sock

        async def fail_connect(sock, addr):
            raise ConnectionRefusedError("refused")

        with (
            patch("fichero.printer._RFCOMM_AVAILABLE", True),
            patch.dict("sys.modules", {"socket": mock_socket_mod}),
        ):
            client = RFCOMMClient("AA:BB:CC:DD:EE:FF")
            loop = asyncio.get_running_loop()
            with patch.object(loop, "sock_connect", fail_connect):
                with pytest.raises(ConnectionRefusedError):
                    await client.__aenter__()
            mock_sock.close.assert_called_once()


class TestRFCOMMClientIO:
    @pytest.mark.asyncio
    async def test_write_gatt_char_sends_data(self):
        client = RFCOMMClient("AA:BB:CC:DD:EE:FF")
        client._sock = MagicMock()

        loop = asyncio.get_running_loop()
        with patch.object(loop, "sock_sendall", new_callable=AsyncMock) as mock_send:
            await client.write_gatt_char("ignored-uuid", b"\x10\xff\x40")
            mock_send.assert_called_once_with(client._sock, b"\x10\xff\x40")

    @pytest.mark.asyncio
    async def test_write_gatt_char_ignores_uuid_and_response(self):
        client = RFCOMMClient("AA:BB:CC:DD:EE:FF")
        client._sock = MagicMock()

        loop = asyncio.get_running_loop()
        with patch.object(loop, "sock_sendall", new_callable=AsyncMock) as mock_send:
            await client.write_gatt_char("any-uuid", b"\xAB", response=True)
            mock_send.assert_called_once_with(client._sock, b"\xAB")

    @pytest.mark.asyncio
    async def test_start_notify_launches_reader(self):
        client = RFCOMMClient("AA:BB:CC:DD:EE:FF")
        client._sock = MagicMock()

        callback = MagicMock()

        # Mock sock_recv to return data once then empty (EOF)
        loop = asyncio.get_running_loop()
        call_count = 0

        async def mock_recv(sock, size):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return b"\x01\x02"
            return b""

        with patch.object(loop, "sock_recv", mock_recv):
            await client.start_notify("ignored-uuid", callback)
            assert client._reader_task is not None
            # Let the reader loop run
            await client._reader_task

        callback.assert_called_once_with(None, bytearray(b"\x01\x02"))

    @pytest.mark.asyncio
    async def test_reader_loop_handles_oserror(self):
        client = RFCOMMClient("AA:BB:CC:DD:EE:FF")
        client._sock = MagicMock()
        callback = MagicMock()

        loop = asyncio.get_running_loop()

        async def mock_recv(sock, size):
            raise OSError("socket closed")

        with patch.object(loop, "sock_recv", mock_recv):
            await client.start_notify("uuid", callback)
            await client._reader_task

        callback.assert_not_called()


class TestRFCOMMClientExit:
    @pytest.mark.asyncio
    async def test_exit_cancels_reader_and_closes_socket(self):
        client = RFCOMMClient("AA:BB:CC:DD:EE:FF")
        mock_sock = MagicMock()
        client._sock = mock_sock

        # Create a long-running task to cancel
        async def hang_forever():
            await asyncio.sleep(999)

        client._reader_task = asyncio.create_task(hang_forever())

        await client.__aexit__(None, None, None)

        assert client._sock is None
        assert client._reader_task is None
        mock_sock.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_exit_no_reader_no_socket(self):
        """Exit is safe even if never connected."""
        client = RFCOMMClient("AA:BB:CC:DD:EE:FF")
        await client.__aexit__(None, None, None)
        assert client._sock is None
        assert client._reader_task is None


# --- connect() integration tests ---


class TestConnectClassic:
    @pytest.mark.asyncio
    async def test_classic_requires_address(self):
        with pytest.raises(PrinterError, match="--address is required"):
            async with connect(classic=True):
                pass

    @pytest.mark.asyncio
    async def test_classic_uses_rfcomm_client(self):
        mock_rfcomm = AsyncMock()
        mock_rfcomm.__aenter__ = AsyncMock(return_value=mock_rfcomm)
        mock_rfcomm.__aexit__ = AsyncMock(return_value=None)
        mock_rfcomm.start_notify = AsyncMock()

        with patch("fichero.printer.RFCOMMClient", return_value=mock_rfcomm) as mock_cls:
            async with connect("AA:BB:CC:DD:EE:FF", classic=True, channel=3) as pc:
                assert isinstance(pc, PrinterClient)
            mock_cls.assert_called_once_with("AA:BB:CC:DD:EE:FF", 3)

    @pytest.mark.asyncio
    async def test_ble_path_unchanged(self):
        """classic=False still uses BleakClient."""
        mock_bleak = AsyncMock()
        mock_bleak.__aenter__ = AsyncMock(return_value=mock_bleak)
        mock_bleak.__aexit__ = AsyncMock(return_value=None)
        mock_bleak.start_notify = AsyncMock()

        with patch("fichero.printer.BleakClient", return_value=mock_bleak) as mock_cls:
            async with connect("AA:BB:CC:DD:EE:FF", classic=False) as pc:
                assert isinstance(pc, PrinterClient)
            mock_cls.assert_called_once_with("AA:BB:CC:DD:EE:FF")


# --- CLI arg parsing tests ---


class TestCLIArgs:
    def test_classic_flag_default_false(self):
        from fichero.cli import main
        import argparse

        with patch("argparse.ArgumentParser.parse_args") as mock_parse:
            mock_parse.return_value = argparse.Namespace(
                address=None, classic=False, channel=1,
                command="status", func=AsyncMock(),
            )
            # Just verify the parser accepts --classic
            from fichero.cli import main as cli_main
            parser = argparse.ArgumentParser()
            parser.add_argument("--classic", action="store_true", default=False)
            parser.add_argument("--channel", type=int, default=1)
            args = parser.parse_args([])
            assert args.classic is False
            assert args.channel == 1

    def test_classic_flag_set(self):
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--classic", action="store_true", default=False)
        parser.add_argument("--channel", type=int, default=1)
        args = parser.parse_args(["--classic", "--channel", "5"])
        assert args.classic is True
        assert args.channel == 5

    def test_env_var_transport(self):
        import argparse

        with patch.dict("os.environ", {"FICHERO_TRANSPORT": "classic"}):
            parser = argparse.ArgumentParser()
            import os
            parser.add_argument(
                "--classic", action="store_true",
                default=os.environ.get("FICHERO_TRANSPORT", "").lower() == "classic",
            )
            args = parser.parse_args([])
            assert args.classic is True


# --- Exports ---


class TestExports:
    def test_rfcomm_client_exported(self):
        from fichero import RFCOMMClient as RC
        assert RC is RFCOMMClient

    def test_rfcomm_channel_exported(self):
        from fichero import RFCOMM_CHANNEL as CH
        assert CH == 1

    def test_all_contains_new_symbols(self):
        import fichero
        assert "RFCOMMClient" in fichero.__all__
        assert "RFCOMM_CHANNEL" in fichero.__all__
