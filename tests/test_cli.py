"""CLI argument handling; commands are mocked, so no printer is contacted."""

from unittest.mock import AsyncMock, patch

import pytest

from fichero.cli import main


@pytest.mark.parametrize(
    "arguments",
    [
        ["--usb", "text", "hello", "--paper", "black"],
        ["--usb", "text", "hello", "--paper", "2"],
        ["--usb", "--classic", "text", "hello"],
        ["--usb", "--address", "AA:BB:CC:DD:EE:FF", "text", "hello"],
        ["--serial", "x", "info"],
        ["--classic", "discover"],
        ["--address", "AA:BB:CC:DD:EE:FF", "discover"],
        ["--usb", "text", "hello", "--copies", "0"],
    ],
)
def test_cli_rejects_unsupported(arguments):
    with (
        patch.dict("os.environ", {}, clear=True),
        patch("sys.argv", ["fichero"] + arguments),
        pytest.raises(SystemExit) as exc,
    ):
        main()
    assert exc.value.code == 2


def test_cli_usb_print_dispatch():
    with (
        patch.dict("os.environ", {}, clear=True),
        patch(
            "sys.argv",
            ["fichero", "--usb", "--serial", "example", "text", "Hello USB!"],
        ),
        patch("fichero.cli.cmd_text", new_callable=AsyncMock) as command,
    ):
        main()
    args = command.call_args.args[0]
    assert args.usb and args.serial == "example" and args.text == ["Hello USB!"]


@pytest.mark.parametrize(
    "arguments,address,classic",
    [
        (["--usb", "text", "hi"], None, False),
        (["text", "hi"], "AA:BB:CC:DD:EE:FF", True),
    ],
)
def test_cli_env_defaults_apply_to_bluetooth_only(arguments, address, classic):
    env = {"FICHERO_ADDR": "AA:BB:CC:DD:EE:FF", "FICHERO_TRANSPORT": "classic"}
    with (
        patch.dict("os.environ", env, clear=True),
        patch("sys.argv", ["fichero"] + arguments),
        patch("fichero.cli.cmd_text", new_callable=AsyncMock) as command,
    ):
        main()
    args = command.call_args.args[0]
    assert args.address == address and args.classic is classic


@pytest.mark.parametrize("arguments", [["discover"], ["--usb", "discover"]])
def test_cli_discover_implies_usb(arguments):
    env = {"FICHERO_ADDR": "AA:BB:CC:DD:EE:FF", "FICHERO_TRANSPORT": "classic"}
    with (
        patch.dict("os.environ", env, clear=True),
        patch("sys.argv", ["fichero"] + arguments),
        patch("fichero.cli.cmd_discover", new_callable=AsyncMock) as command,
    ):
        main()
    args = command.call_args.args[0]
    assert args.usb and args.address is None and not args.classic


@pytest.mark.parametrize("paper", ["gap", "0", "unknown"])
def test_cli_usb_accepts_papers_that_resolve_to_gap(paper):
    with (
        patch.dict("os.environ", {}, clear=True),
        patch("sys.argv", ["fichero", "--usb", "text", "hi", "--paper", paper]),
        patch("fichero.cli.cmd_text", new_callable=AsyncMock) as command,
    ):
        main()
    assert command.call_args.args[0].paper == 0
