import { BYTES_PER_ROW, CHUNK_DELAY_MS, CHUNK_SIZE, CMD } from "./constants";
import { Utils } from "./utils";
import type { EncodedImage, LabelType, PrintProgressEvent } from "./types";

export interface PrintTaskOptions {
  totalPages: number;
  density: number;
  speed: number;
  labelType: LabelType;
  statusPollIntervalMs: number;
  statusTimeoutMs: number;
}

export abstract class AbstractPrintTask {
  abstract printInit(): Promise<void>;
  abstract printPage(image: EncodedImage, quantity: number): Promise<void>;
  abstract waitForFinished(): Promise<void>;
  abstract printEnd(): Promise<void>;
}

type SendFn = (data: readonly number[] | number[] | Uint8Array, wait?: boolean, timeout?: number) => Promise<Uint8Array>;
type SendChunkedFn = (data: Uint8Array) => Promise<void>;
type EmitProgressFn = (event: PrintProgressEvent) => void;

export class FicheroPrintTask extends AbstractPrintTask {
  private opts: PrintTaskOptions;
  private sendCmd: SendFn;
  private sendChunked: SendChunkedFn;
  private emitProgress: EmitProgressFn;

  constructor(
    opts: PrintTaskOptions,
    sendCmd: SendFn,
    sendChunked: SendChunkedFn,
    emitProgress: EmitProgressFn,
  ) {
    super();
    this.opts = opts;
    this.sendCmd = sendCmd;
    this.sendChunked = sendChunked;
    this.emitProgress = emitProgress;
  }

  async printInit(): Promise<void> {
    // Check status
    const statusResp = await this.sendCmd(CMD.getStatus, true);
    if (statusResp.length > 0) {
      const sb = statusResp[statusResp.length - 1];
      if (sb & 0x02) throw new Error("Cover is open");
      if (sb & 0x04) throw new Error("No paper loaded");
      if (sb & 0x50) throw new Error("Printer overheated");
    }

    // Set density
    await this.sendCmd(CMD.setDensity(this.opts.density), true);
    await Utils.sleep(100);
  }

  async printPage(image: EncodedImage, quantity: number): Promise<void> {
    const paperTypeMap: Record<number, number> = { 1: 0, 2: 1, 3: 2 };
    const paperByte = paperTypeMap[this.opts.labelType] ?? 0;

    for (let copy = 0; copy < quantity; copy++) {
      // Paper type
      await this.sendCmd(CMD.setPaperType(paperByte), true);
      await Utils.sleep(50);

      // Wake up (12 null bytes)
      await this.sendCmd(new Array(12).fill(0));
      await Utils.sleep(50);

      // Enable printer
      await this.sendCmd(Array.from(CMD.enablePrinter));
      await Utils.sleep(50);

      // Raster header: GS v 0 mode xL xH yL yH
      const yL = image.rows & 0xff;
      const yH = (image.rows >> 8) & 0xff;
      const header = new Uint8Array([0x1d, 0x76, 0x30, 0x00, BYTES_PER_ROW, 0x00, yL, yH]);

      const payload = new Uint8Array(header.length + image.rowsData.length);
      payload.set(header, 0);
      payload.set(image.rowsData, header.length);

      await this.sendChunked(payload);
      await Utils.sleep(500);

      // Form feed
      await this.sendCmd(Array.from(CMD.formFeed));
      await Utils.sleep(300);

      this.emitProgress({
        page: copy + 1,
        pagePrintProgress: 100,
        pageFeedProgress: 0,
      });

      // Stop print and wait for response
      await this.sendCmd(Array.from(CMD.stopPrint), true, 60000);

      this.emitProgress({
        page: copy + 1,
        pagePrintProgress: 100,
        pageFeedProgress: 100,
      });
    }
  }

  async waitForFinished(): Promise<void> {
    // Already waited during printPage for each copy's stop response
  }

  async printEnd(): Promise<void> {
    // No additional cleanup needed
  }
}
