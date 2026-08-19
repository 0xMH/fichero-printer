import { dsvFormat, type DSVRowArray } from "d3-dsv";

export const CSV_DEFAULT_DELIMITER = ",";
const CSV_IDENTIFIER_RX = /^[A-Za-z_$][\w$]*$/;

export const makeCsvColumnAliases = (columnCount: number): string[] =>
  Array.from({ length: columnCount }, (_, index) => `col${index + 1}`);

export const normalizeCsvDelimiter = (delimiter?: string): string => {
  if (delimiter === undefined || delimiter === "") {
    return CSV_DEFAULT_DELIMITER;
  }

  if (delimiter === "\\t" || delimiter.toLowerCase() === "tab") {
    return "\t";
  }

  return Array.from(delimiter)[0] ?? CSV_DEFAULT_DELIMITER;
};

export const detectCsvDelimiter = (data: string): string | undefined => {
  const firstLine = normalizeCsvData(data)
    .split(/\r?\n/)
    .find((line) => line.trim() !== "");

  if (firstLine === undefined) {
    return undefined;
  }

  const candidates = [",", ";", "\t"];
  const best = candidates
    .map((delimiter) => ({
      delimiter,
      count: firstLine.split(delimiter).length - 1,
    }))
    .sort((a, b) => b.count - a.count)[0];

  return best !== undefined && best.count > 0 ? best.delimiter : undefined;
};

export const cleanCsvCell = (value: string): string => {
  const trimmed = value.trim();
  const first = trimmed[0];
  const last = trimmed[trimmed.length - 1];

  if (trimmed.length >= 2 && ((first === "\"" && last === "\"") || (first === "'" && last === "'"))) {
    return trimmed.slice(1, -1).replaceAll(`${first}${first}`, first);
  }

  return trimmed.replace(/^["']+|["']+$/g, "");
};

export const normalizeCsvData = (data: string): string => {
  return data
    .split(/\r?\n/)
    .filter((line) => {
      const trimmed = line.trim();
      return trimmed !== "\"" && trimmed !== "'";
    })
    .join("\n");
};

export const detectCsvHasHeader = (data: string, delimiter?: string): boolean => {
  const parser = dsvFormat(normalizeCsvDelimiter(delimiter));
  const rows = parser.parseRows(normalizeCsvData(data), (row) => row.map(cleanCsvCell)).filter((row) => row.length > 0);
  const firstRow = rows[0] ?? [];

  return firstRow.length > 0 && firstRow.every((cell) => CSV_IDENTIFIER_RX.test(cell));
};

export const parseCsvData = (
  data: string,
  delimiter?: string,
  hasHeader: boolean = true,
  oneItemPerCell: boolean = false,
): DSVRowArray<string> => {
  const parser = dsvFormat(normalizeCsvDelimiter(delimiter));
  const normalizedData = normalizeCsvData(data);

  if (oneItemPerCell) {
    const rows = parser
      .parseRows(normalizedData, (row) => row.map(cleanCsvCell))
      .flat()
      .filter((cell) => cell !== "");
    const normalized: DSVRowArray<string> = Object.assign([], { columns: ["col1"] });

    for (const cell of rows) {
      normalized.push({ col1: cell });
    }

    return normalized;
  }

  if (!hasHeader) {
    const rows = parser.parseRows(normalizedData, (row) => row.map(cleanCsvCell)).filter((row) => row.length > 0);
    const columnCount = Math.max(0, ...rows.map((row) => row.length));
    const aliases = makeCsvColumnAliases(columnCount);
    const normalized: DSVRowArray<string> = Object.assign([], { columns: aliases });

    for (const row of rows) {
      const cleanRow: Record<string, string> = {};

      aliases.forEach((alias, index) => {
        cleanRow[alias] = row[index] ?? "";
      });

      normalized.push(cleanRow);
    }

    return normalized;
  }

  const parsed = parser.parse(normalizedData);
  const columns = parsed.columns.map(cleanCsvCell);
  const normalized: DSVRowArray<string> = Object.assign([], { columns });

  for (const row of parsed) {
    const cleanRow: Record<string, string> = {};

    parsed.columns.forEach((sourceColumn, index) => {
      cleanRow[columns[index]] = cleanCsvCell(row[sourceColumn] ?? "");
    });

    normalized.push(cleanRow);
  }

  return normalized;
};
