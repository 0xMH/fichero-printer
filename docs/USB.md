# Fichero D11s (AiYin) - USB Transport

Verified against hardware (D11s, firmware 2.4.9, `09c5:0200`) on Linux.
See [PROTOCOL.md](PROTOCOL.md) for the command set, which is unchanged over USB.

## Device

- USB ID: `09c5:0200`; other VID/PIDs are not supported
- The firmware version is not checked; only 2.4.9 has been tested
- One Printer Class interface (class 7, subclass 1, protocol 2 bidirectional),
  alternate setting 0
- Bulk OUT `0x01` for commands and raster data, bulk IN `0x81` for replies
- The transport uses the active configuration and validates the endpoints
  without resetting the device (a reset can disrupt CUPS)

## Replies

The printer answers the same commands as over Bluetooth, with the same reply
bytes, on bulk IN:

| Command | Reply |
|---|---|
| `10 FF 40` status | 1 byte, e.g. `0x00` ready, `0x06` cover open + no paper |
| `10 FF 10 00 nn` density | `OK` |
| `10 FF 84 nn` paper type | `OK` |
| `10 FF FE 45` stop | `0xAA` when idle; `OK` once a printed label has finished |
| `10 FF 20 Fx`, `10 FF 50 F1`, `10 FF 70` info | Same strings as Bluetooth |

Raster data, wakeup, enable and form feed get no reply.

Observed behaviour the transport handles:

- **Completion timing.** After a printed label, the stop reply arrives once the
  label has finished (about 2.3s for a 30mm label), so copies are paced by the
  printer rather than sent back to back.
- **Replies survive reconnection.** Unread replies remain queued across closing
  the device and `usblp` rebinding. They are discarded on connect so they are
  not taken as replies to new commands.
- **Unread replies can be lost.** When nothing reads bulk IN during a
  multi-copy job, some replies are dropped (5 of 7 arrived), although every
  label prints. A reader thread therefore reads bulk IN for the whole session.
- **Framing.** One read can hold several replies (`OKOKOK`), and a long reply
  (`10 FF 70`) can span two reads about 30ms apart.

A timeout or partial write leaves the print outcome unknown; inspect the
printer before retrying to avoid duplicate labels.

## Printer Class status byte

The [USB Printer Class specification](https://www.usb.org/sites/default/files/usbprint11a021811.pdf)
defines a port status byte separate from the proprietary status: paper-empty
(bit 5), selected (bit 4) and not-error (bit 3). The observed `0x18` does not
show that the D11s paper/cover sensors are reflected in it, so it is not used;
readiness comes from the proprietary `10 FF 40` query.

## Linux permissions

The README's `uaccess` rule grants access to the active local seat, not
generally to SSH sessions or services. On headless systems, an administrator
can instead create a dedicated `fichero` group, add the printing user to it,
and use this rule (log in again after changing group membership):

```udev
SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", ATTR{idVendor}=="09c5", ATTR{idProduct}=="0200", GROUP="fichero", MODE="0660"
```

## Contention with usblp and CUPS

Close other printer clients before use. The transport temporarily detaches
`usblp` if it owns the interface and restores it on exit, including after
errors; if restoration fails, the error or warning is reported and the device
should be reconnected.

A busy error can indicate another libusb client or a CUPS backend using the
printer. Avoid simultaneous CUPS jobs, and check both distribution and Snap
CUPS installations; pause the relevant queue yourself if needed. This driver
does not change queues, PPDs or system services, and does not require a CUPS
driver.

## Other platforms

Not hardware-tested. macOS requires libusb (for example `brew install libusb`).
Windows requires libusb plus a compatible interface driver such as WinUSB, which
can replace OS printer access. Missing PyUSB and missing libusb produce distinct
errors.

## Library use

Use `connect(usb=True, serial=None)` with the existing print pipeline
(`fichero.cli.do_print`), or `USBClient` directly. `discover_usb()` returns
serial/bus/address records without claiming interfaces, and
`PrinterClient.is_usb` identifies the transport. All protocol methods behave as
over Bluetooth; transport failures raise `PrinterError` subclasses.
