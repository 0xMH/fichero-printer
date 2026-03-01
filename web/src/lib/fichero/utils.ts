import type { AvailableTransports } from "./types";

export class Utils {
  static bufToHex(buf: Uint8Array | number[], separator: string = " "): string {
    const arr = buf instanceof Uint8Array ? Array.from(buf) : buf;
    return arr.map((b) => b.toString(16).padStart(2, "0")).join(separator);
  }

  static sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  static getAvailableTransports(): AvailableTransports {
    return {
      webBluetooth: typeof navigator !== "undefined" && "bluetooth" in navigator,
    };
  }
}
