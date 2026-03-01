export enum LabelType {
  WithGaps = 1,
  Black = 2,
  Continuous = 3,
}

export enum SoundSettingsItemType {
  BluetoothConnectionSound = 1,
  PowerSound = 2,
}

export enum RequestCommandId {
  GetModel = 0x20f0,
  GetFirmware = 0x20f1,
  GetSerial = 0x20f2,
  GetBattery = 0x50f1,
  GetStatus = 0x0040,
  SetDensity = 0x1000,
  SetPaperType = 0x0084,
  EnablePrinter = 0xfe01,
  StopPrint = 0xfe45,
  FormFeed = 0x1d0c,
  RasterData = 0x7630,
}

export enum ResponseCommandId {
  Ok = 0x4f4b,
  Ack = 0x00aa,
  Error = 0x00ff,
}

export type PrintDirection = "left" | "top";

export interface PrinterInfo {
  modelId?: string;
  firmware?: string;
  serial?: string;
  battery?: number;
  charging?: boolean;
  [key: string]: string | number | boolean | undefined;
}

export interface PrinterModelMeta {
  model: string;
  printheadPixels: number;
  printDirection: PrintDirection;
  densityMin: number;
  densityMax: number;
  densityDefault: number;
  paperTypes: LabelType[];
}

export interface HeartbeatData {
  chargeLevel?: number;
  charging?: boolean;
  statusByte?: number;
  paperRfidSuccess?: boolean;
  ribbonRfidSuccess?: boolean;
}

export interface RfidInfo {
  [key: string]: string | number | boolean | undefined;
}

export interface AvailableTransports {
  webBluetooth: boolean;
}

export interface ConnectionInfo {
  deviceName?: string;
}

export interface EncodedImage {
  cols: number;
  rows: number;
  rowsData: Uint8Array;
}

export interface PrintProgressEvent {
  page: number;
  pagePrintProgress: number;
  pageFeedProgress: number;
}

export interface FirmwareProgressEvent {
  currentChunk: number;
  totalChunks: number;
}

export interface Packet {
  command: number;
  toBytes(): Uint8Array;
}

export const printTaskNames = ["B1", "D110M_V4"] as const;
export type PrintTaskName = (typeof printTaskNames)[number];
