# fichero-printer

Web GUI, Python CLI, and protocol documentation for the Fichero D11s thermal label printer.

Blog post: [Reverse Engineering Action's Cheap Fichero Labelprinter](https://blog.dbuglife.com/reverse-engineering-fichero-label-printer/)

The [Fichero](https://www.action.com/nl-nl/p/3212141/fichero-labelprinter/) is a cheap Bluetooth thermal label printer sold at Action. Internally it's an AiYin D11s made by Xiamen Print Future Technology. The official app is closed-source and doesn't expose the protocol, so this project reverse-engineers it from the decompiled APK.

## The printer

- 96px wide printhead, 203 DPI
- Prints 1-bit raster images onto self-adhesive labels (14mm x 30mm default)
- Connects via BLE or Classic Bluetooth SPP
- 18500 Li-Ion battery (1200mAh), USB-C charging
- Bluetooth names: `FICHERO_5836`, `D11s_`

## Why not just use the app?

The Fichero app (`com.lj.fichero`) asks for 26 permissions. For a label printer. The notable ones:

```
ACCESS_FINE_LOCATION         Your precise GPS location
ACCESS_COARSE_LOCATION       Your approximate location
CAMERA                       Your camera
READ_EXTERNAL_STORAGE        Your files
WRITE_EXTERNAL_STORAGE       Your files (write)
READ_MEDIA_IMAGES            Your photos
INTERNET                     Full internet access
ACCESS_WIFI_STATE            Your WiFi info
CHANGE_WIFI_STATE            Change your WiFi settings
CHANGE_WIFI_MULTICAST_STATE  Multicast on your network
AD_ID                        Your advertising ID
ACCESS_ADSERVICES_AD_ID      More ad tracking
ACCESS_ADSERVICES_ATTRIBUTION  Ad attribution tracking
BIND_GET_INSTALL_REFERRER    Where you installed from
```

Some of these are reasonable. The location permissions exist because of how Android handles Bluetooth. Bluetooth signals can reveal where you physically are, think retail stores using Bluetooth beacons to track which aisle you're standing in. So Android won't let any app scan for Bluetooth devices unless it also has location permission. That's not the app being sneaky. That's Android being cautious.

The camera makes sense too. The app lets you scan barcodes and photograph things to print on labels.

The WiFi permissions are baggage from the underlying SDK. It powers over 159 different printer models, some of which connect over WiFi. The Fichero doesn't use WiFi at all, but the permissions are baked into the shared code.

Then there are four permissions that have nothing to do with printing. Your advertising ID is a unique number assigned to your phone that follows you across every app, letting ad networks build a profile of what you do. The app also wants ad attribution tracking (which apps you installed after seeing an ad) and your install referrer (how you found the app store listing). That's a label printer quietly feeding your activity to an ad network.

The package name is `com.lj.fichero` but the SDK inside is from a company called LuckPrinter (`com.luckprinter.sdk_new`). The app is what's called a white-label product: a generic app rebranded with the Fichero name and logo. The same codebase runs receipt printers, A4 thermal printers, and industrial label makers. It supports 159+ printer models across four manufacturers. Your little label printer's app is just a skin on top.

One more reason to ditch the app and talk to the printer directly.

## Web GUI

Try it at https://0xmh.github.io/fichero-printer/ - a full label designer with text, images, barcodes, QR codes, and drag-and-drop canvas editing. Built with Svelte 5 and Fabric.js, ported from the NiimBlue project (MIT).

Click the Bluetooth icon, pair with the printer, and start designing. Labels save to browser localStorage. Export as JSON or PNG.

Requires Web Bluetooth, so Chrome/Edge/Opera only. Firefox and Safari don't support it.

## CLI Setup

Requires Python 3.10+ and uv. Turn on the printer and run:

```
uv run fichero info
```

This auto-discovers the printer via BLE scan. To skip scanning on subsequent runs, find your printer's address from the scan output and save it:

```
export FICHERO_ADDR=AA:BB:CC:DD:EE:FF
```

You can also pass it per-command:

```
uv run fichero --address AA:BB:CC:DD:EE:FF info
```

## CLI Usage

```
uv run fichero --help
```

### Printing

```
uv run fichero text "Hello World"
uv run fichero text "Fragile" --density 2 --copies 3
uv run fichero text "Big Label" --font-size 40 --label-height 180
uv run fichero image label.png
uv run fichero image label.png --density 1 --copies 2
```

Density: 0=light, 1=medium (default), 2=thick.

Text labels accept `--font-size` (default 24) and `--label-height` in pixels (default 240).

### Device info

```
uv run fichero info
uv run fichero status
```

### Settings

```
uv run fichero set density 2
uv run fichero set shutdown 30
uv run fichero set paper gap
```

- `density` - how dark the print is. 0 is faint, 1 is normal, 2 is the darkest. Higher density uses more battery and can smudge on some label stock.
- `shutdown` - how many minutes the printer waits before turning itself off when idle (1-480). Set it higher if you're tired of turning it back on between prints.
- `paper` - what kind of label stock you're using. `gap` is the default, for labels with spacing between them (the printer detects the gap to know where to stop). `black` is for rolls with a black mark between labels. `continuous` is for receipt-style rolls with no markings.

## Library Usage

```python
import asyncio
from fichero import connect, PrinterNotFound

async def main():
    async with connect() as pc:
        info = await pc.get_info()
        print(info)

asyncio.run(main())
```

The package exports `PrinterClient`, `connect`, `PrinterError`, `PrinterNotFound`, `PrinterTimeout`, `PrinterNotReady`, and `PrinterStatus`.

## TODO

- [ ] Emoji support in text labels. The default Pillow font has no emoji glyphs, so they render as squares. Needs two-pass rendering: split text into emoji/non-emoji segments, render emoji with Apple Color Emoji (macOS) or Noto Color Emoji (Linux) using `embedded_color=True`, then composite onto the label.

## Protocol and reverse engineering

See [docs/PROTOCOL.md](docs/PROTOCOL.md) for the full command reference, print sequence, and how this was reverse-engineered.

## License

MIT
