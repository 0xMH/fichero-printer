<script lang="ts">
  import { tr } from "$/utils/i18n";
  import MdIcon from "$/components/basic/MdIcon.svelte";
  import { type CsvParams } from "$/types";
  import { csvData } from "$/stores";
  import { CSV_PLACEHOLDER } from "$/defaults";
  import { FileUtils } from "$/utils/file_utils";
  import { Toasts } from "$/utils/toasts";
  import {
    CSV_DEFAULT_DELIMITER,
    detectCsvDelimiter,
    detectCsvHasHeader,
    normalizeCsvDelimiter,
    parseCsvData,
  } from "$/utils/csv";

  interface Props {
    enabled: boolean;
    onPlaceholderPicked: (name: string) => void;
    onDataLoaded?: (placeholders: string[], hasHeader: boolean, replaceCurrentTemplate?: boolean) => void;
    activePlaceholders?: string[];
    maxActivePlaceholders?: number;
  }

  let {
    enabled = $bindable(),
    onPlaceholderPicked,
    onDataLoaded,
    activePlaceholders = [],
    maxActivePlaceholders = 5,
  }: Props = $props();

  let placeholders = $state<string[]>([]);
  let rows = $state<number>(0);
  let pickedFileName = $state<string>("");
  let hasHeaderManuallyChanged = $state(false);

  const parse = (csv: CsvParams) => {
    const result = parseCsvData(csv.data, csv.delimiter, csv.hasHeader ?? true, csv.oneItemPerCell ?? false);
    placeholders = result.columns;
    rows = result.length;
  };

  const refreshData = (replaceCurrentTemplate: boolean = false) => {
    const result = parseCsvData(
      $csvData.data,
      $csvData.delimiter,
      $csvData.hasHeader ?? true,
      $csvData.oneItemPerCell ?? false,
    );
    onDataLoaded?.(result.columns, $csvData.hasHeader ?? true, replaceCurrentTemplate);
  };

  const delimiterInputValue = () => {
    const delimiter = normalizeCsvDelimiter($csvData.delimiter);
    return delimiter === "\t" ? "\\t" : delimiter;
  };

  const setDelimiter = (value: string) => {
    $csvData.delimiter = value || CSV_DEFAULT_DELIMITER;
    enabled = true;
    refreshData($csvData.oneItemPerCell ?? false);
  };

  const setHasHeader = (value: boolean) => {
    $csvData.hasHeader = value;
    hasHeaderManuallyChanged = true;
    enabled = true;
    refreshData($csvData.oneItemPerCell ?? false);
  };

  const setOneItemPerCell = (value: boolean) => {
    $csvData.oneItemPerCell = value;
    enabled = true;
    refreshData(value);
  };

  const updateCsvData = (value: string) => {
    $csvData.data = value;
    const detectedDelimiter = detectCsvDelimiter(value);

    if (detectedDelimiter !== undefined) {
      $csvData.delimiter = detectedDelimiter;
    }

    if (!hasHeaderManuallyChanged) {
      $csvData.hasHeader = detectCsvHasHeader(value, $csvData.delimiter);
    }

    enabled = true;
    refreshData($csvData.oneItemPerCell ?? false);
  };

  const loadCsvFile = async () => {
    try {
      const files = await FileUtils.pickFileAsync("csv", false);
      const file = files[0];
      $csvData.data = await file.text();
      $csvData.delimiter = detectCsvDelimiter($csvData.data) ?? $csvData.delimiter;
      $csvData.hasHeader = detectCsvHasHeader($csvData.data, $csvData.delimiter);
      hasHeaderManuallyChanged = false;
      pickedFileName = file.name;
      enabled = true;
      refreshData($csvData.oneItemPerCell ?? false);
    } catch (e) {
      Toasts.error(e);
    }
  };

  $effect(() => {
    parse($csvData);
  });
</script>

<div class="dropdown">
  <button
    class="btn btn-sm btn-{enabled ? 'warning' : 'secondary'}"
    data-bs-toggle="dropdown"
    data-bs-auto-close="outside"
    title={$tr("params.csv.title")}>
    <MdIcon icon="dataset" />
  </button>
  <div class="dropdown-menu">
    <h6 class="dropdown-header">{$tr("params.csv.title")}</h6>
    <div class="p-3 text-body-secondary">
      <div class="form-check form-switch">
        <input class="form-check-input" type="checkbox" role="switch" id="enabled" bind:checked={enabled} />
        <label class="form-check-label" for="enabled">{$tr("params.csv.enabled")}</label>
      </div>

      <div class="mt-3">
        {$tr("params.csv.tip")}
      </div>

      <button class="btn btn-sm btn-outline-secondary mt-3" type="button" onclick={loadCsvFile}>
        <MdIcon icon="upload_file" />
        Load CSV file
      </button>
      {#if pickedFileName}
        <div class="small text-body-secondary mt-1">{pickedFileName}</div>
      {/if}

      <div class="input-group input-group-sm mt-3">
        <span class="input-group-text">Separator</span>
        <input
          class="form-control"
          maxlength="3"
          value={delimiterInputValue()}
          oninput={(e) => setDelimiter(e.currentTarget.value)}
          placeholder="," />
        <button class="btn btn-outline-secondary" type="button" onclick={() => setDelimiter(",")}>Comma</button>
        <button class="btn btn-outline-secondary" type="button" onclick={() => setDelimiter(";")}>Semicolon</button>
        <button class="btn btn-outline-secondary" type="button" onclick={() => setDelimiter("\\t")}>Tab</button>
      </div>

      <div class="form-check form-switch mt-3">
        <input
          class="form-check-input"
          type="checkbox"
          role="switch"
          id="csv-has-header"
          checked={$csvData.hasHeader ?? true}
          onchange={(e) => setHasHeader(e.currentTarget.checked)} />
        <label class="form-check-label" for="csv-has-header">First row contains column names</label>
      </div>

      <div class="form-check form-switch mt-3">
        <input
          class="form-check-input"
          type="checkbox"
          role="switch"
          id="csv-one-item-per-cell"
          checked={$csvData.oneItemPerCell ?? false}
          onchange={(e) => setOneItemPerCell(e.currentTarget.checked)} />
        <label class="form-check-label" for="csv-one-item-per-cell">Separated values are individual labels</label>
      </div>

      <textarea
        class="dsv form-control my-3"
        placeholder={CSV_PLACEHOLDER}
        value={$csvData.data}
        oninput={(e) => updateCsvData(e.currentTarget.value)}></textarea>

      <div class="placeholders pt-1">
        {$tr("params.csv.rowsfound")} <strong>{rows}</strong>
      </div>
      <div class="placeholders pt-1">
        {$tr("params.csv.placeholders")}
        {#each placeholders as p (p)}
          {@const active = activePlaceholders.includes(p)}
          {@const disabled = !active && activePlaceholders.length >= maxActivePlaceholders}
          <button
            class="btn btn-sm btn-{active ? 'info' : 'outline-info'} placeholder-toggle px-1 py-0"
            aria-pressed={active}
            {disabled}
            title={disabled ? `Remove another column first. Stickers can show up to ${maxActivePlaceholders} rows.` : ""}
            onclick={() => onPlaceholderPicked(p)}
            >{`{${p}}`}
          </button>
        {/each}
      </div>
    </div>
  </div>
</div>

<style>
  .dropdown-menu {
    width: 100vw;
    max-width: 450px;
  }
  textarea.dsv {
    font-family: monospace;
    min-height: 240px;
  }
  .placeholder-toggle {
    align-items: center;
    display: inline-flex;
    justify-content: center;
    line-height: 1.2;
    min-height: 1.5rem;
  }
</style>
