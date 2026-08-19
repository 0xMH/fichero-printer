<script lang="ts">
  import Dropdown from "bootstrap/js/dist/dropdown";
  import * as fabric from "fabric";
  import { onDestroy, onMount, tick } from "svelte";
  import { Barcode } from "$/fabric-object/barcode";
  import { QRCode } from "$/fabric-object/qrcode";
  import { iconCodepoints, type MaterialIcon } from "$/styles/mdi_icons";
  import { automation, connectionState, csvData, loadedFonts } from "$/stores";
  import {
    type ExportedLabelTemplate,
    type FabricJson,
    type LabelProps,
    type MoveDirection,
    type OjectType,
  } from "$/types";
  import { FileUtils } from "$/utils/file_utils";
  import { tr } from "$/utils/i18n";
  import { LabelDesignerObjectHelper } from "$/utils/label_designer_object_helper";
  import { LocalStoragePersistence } from "$/utils/persistence";
  import { Toasts } from "$/utils/toasts";
  import { UndoRedo, type UndoState } from "$/utils/undo_redo";
  import { TextboxExt } from "$/fabric-object/textbox-ext";
  import BarcodeParamsPanel from "$/components/designer-controls/BarcodeParamsControls.svelte";
  import CsvControl from "$/components/designer-controls/CsvControl.svelte";
  import GenericObjectParamsControls from "$/components/designer-controls/GenericObjectParamsControls.svelte";
  import IconPicker from "$/components/designer-controls/IconPicker.svelte";
  import LabelPropsEditor from "$/components/designer-controls/LabelPropsEditor.svelte";
  import MdIcon from "$/components/basic/MdIcon.svelte";
  import ObjectPicker from "$/components/designer-controls/ObjectPicker.svelte";
  import PrintPreview from "$/components/PrintPreview.svelte";
  import QrCodeParamsPanel from "$/components/designer-controls/QRCodeParamsControls.svelte";
  import TextParamsControls from "$/components/designer-controls/TextParamsControls.svelte";
  import VariableInsertControl from "$/components/designer-controls/VariableInsertControl.svelte";
  import { DEFAULT_LABEL_PROPS, GRID_SIZE } from "$/defaults";
  import { LabelDesignerUtils } from "$/utils/label_designer_utils";
  import SavedLabelsMenu from "$/components/designer-controls/SavedLabelsMenu.svelte";
  import { CustomCanvas } from "$/fabric-object/custom_canvas";
  import VectorParamsControls from "$/components/designer-controls/VectorParamsControls.svelte";
  import { CanvasUtils } from "$/utils/canvas_utils";
  import { makeCsvColumnAliases } from "$/utils/csv";

  const CSV_MAX_STICKER_ROWS = 5;

  let htmlCanvas: HTMLCanvasElement;

  let fabricCanvas = $state<CustomCanvas>();
  let labelProps = $state<LabelProps>(DEFAULT_LABEL_PROPS);
  let previewOpened = $state<boolean>(false);
  let selectedObject = $state<fabric.FabricObject | undefined>(undefined);
  let selectedCount = $state<number>(0);
  let editRevision = $state<number>(0);
  let printNow = $state<boolean>(false);
  let csvEnabled = $state<boolean>(false);
  let windowWidth = $state<number>(0);
  let undoState = $state<UndoState>({ undoDisabled: false, redoDisabled: false });

  const undo = new UndoRedo();

  const discardSelection = () => {
    fabricCanvas!.discardActiveObject();
    fabricCanvas!.requestRenderAll();
    selectedObject = undefined;
    selectedCount = 0;
    editRevision = 0;
  };

  const loadLabelData = async (data: ExportedLabelTemplate) => {
    undo.paused = true;
    onUpdateLabelProps(data.label);
    if (data.csv) {
      $csvData = data.csv;
      csvEnabled = true;
    }
    await FileUtils.loadCanvasState(fabricCanvas!, data.canvas);
    undo.paused = false;
  };

  undo.onLabelUpdate = loadLabelData;
  undo.onStateUpdate = (state: UndoState) => {
    undoState = state;
  };

  const deleteSelected = () => {
    LabelDesignerUtils.deleteSelection(fabricCanvas!);
    discardSelection();
  };

  const cloneSelected = () => {
    LabelDesignerUtils.cloneSelection(fabricCanvas!).then(() => undo.push(fabricCanvas!, labelProps));
  };

  const moveSelected = (direction: MoveDirection, ctrl?: boolean) => {
    LabelDesignerUtils.moveSelection(fabricCanvas!, direction, ctrl);
    undo.push(fabricCanvas!, labelProps);
  };

  const onKeyDown = (e: KeyboardEvent) => {
    const key: string = e.key.toLowerCase();
    // windows and linux users are used to ctrl, mac users use cmd
    const cmdOrCtrl = e.metaKey || e.ctrlKey;

    // Esc
    if (key === "escape") {
      discardSelection();
      return;
    }

    if (LabelDesignerUtils.isAnyInputFocused(fabricCanvas!)) {
      return;
    }

    // Arrows
    if (key.startsWith("arrow")) {
      moveSelected(key.slice("arrow".length) as MoveDirection, cmdOrCtrl);
      return;
    }

    if (e.repeat) {
      return;
    }

    // Ctrl + D
    if (cmdOrCtrl && key === "d") {
      e.preventDefault();
      cloneSelected();
      return;
    }

    // Ctrl + Y, Ctrl + Shift + Z
    if ((cmdOrCtrl && key === "y") || (cmdOrCtrl && e.shiftKey && key === "z")) {
      e.preventDefault();
      if (!undoState.redoDisabled) {
        undo.redo();
      }
      return;
    }

    // Ctrl + Z
    if (cmdOrCtrl && key === "z") {
      e.preventDefault();
      if (!undoState.undoDisabled) {
        undo.undo();
      }
      return;
    }

    // Del
    if (key === "delete" || key === "backspace") {
      deleteSelected();
      return;
    }
  };

  const onUpdateLabelProps = (newProps: LabelProps) => {
    labelProps = newProps;
    fabricCanvas!.setDimensions(labelProps.size);
    fabricCanvas!.virtualZoom(fabricCanvas!.getVirtualZoom());
    try {
      LocalStoragePersistence.saveLastLabelProps(labelProps);
      undo.push(fabricCanvas!, labelProps);
    } catch (e) {
      Toasts.zodErrors(e, "Label parameters save error:");
    }
  };

  const exportCurrentLabel = (): ExportedLabelTemplate => {
    return FileUtils.makeExportedLabel(fabricCanvas!, labelProps, csvEnabled);
  };

  const onLoadRequested = (label: ExportedLabelTemplate) => {
    loadLabelData(label).then(() => undo.push(fabricCanvas!, labelProps));
  };

  const zplImageReady = async (img: Blob) => {
    await LabelDesignerObjectHelper.addImageBlob(fabricCanvas!, img);
    undo.push(fabricCanvas!, labelProps);
  };

  const onObjectPicked = (objectType: OjectType) => {
    const obj = LabelDesignerObjectHelper.addObject(fabricCanvas!, objectType);
    if (obj !== undefined) {
      fabricCanvas!.setActiveObject(obj);
      undo.push(fabricCanvas!, labelProps);
    }
  };

  const onIconPicked = (i: MaterialIcon) => {
    // todo: icon is not vertically centered
    LabelDesignerObjectHelper.addStaticText(fabricCanvas!, String.fromCodePoint(iconCodepoints[i]), {
      fontFamily: "Material Icons",
      fontSize: 100,
    });
    undo.push(fabricCanvas!, labelProps);
  };

  const onSvgIconPicked = (i: string) => {
    LabelDesignerObjectHelper.addSvg(fabricCanvas!, i);
    undo.push(fabricCanvas!, labelProps);
  };

  const openPreview = () => {
    printNow = false;
    previewOpened = true;
  };

  const openPreviewAndPrint = () => {
    printNow = true;
    previewOpened = true;
  };

  const controlValueUpdated = () => {
    if (selectedObject) {
      selectedObject.setCoords();
      selectedObject.dirty = true;
      undo.push(fabricCanvas!, labelProps);
    }
    fabricCanvas!.requestRenderAll();

    // trigger reactivity for controls
    editRevision++;
  };

  const getCanvasForPreview = (): FabricJson => {
    return fabricCanvas!.toJSON();
  };

  const csvTextOptions = () => ({
      width: Math.max(2, labelProps.size.width - 12),
      fontAutoSize: true,
      fontSize: Math.max(12, Math.floor(labelProps.size.height * 0.42)),
      textAlign: "center",
      originX: "left",
      originY: "center",
      left: 6,
      top: labelProps.size.height / 2,
    }) as const;

  const applyCsvTextTemplate = (text: string, target?: TextboxExt): TextboxExt => {
    const obj = target ?? LabelDesignerObjectHelper.addText(fabricCanvas!, text, csvTextOptions());
    obj.set({
      ...csvTextOptions(),
      text,
    });
    fabricCanvas!.setActiveObject(obj);
    selectedObject = obj;
    selectedCount = 1;
    editRevision++;
    obj.setCoords();
    fabricCanvas!.requestRenderAll();
    return obj;
  };

  const defaultTextValues = () => new Set(["", "Text", $tr("editor.default_text")]);

  const isDefaultText = (text?: string): boolean => defaultTextValues().has((text ?? "").trim());

  const csvTemplateLines = (text?: string): string[] => {
    const defaultValues = defaultTextValues();
    return (text ?? "")
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter((line) => line !== "" && !defaultValues.has(line));
  };

  const csvTargetTextbox = (): TextboxExt | undefined => {
    const active = fabricCanvas?.getActiveObject();
    if (active instanceof TextboxExt) {
      return active;
    }

    if (selectedObject instanceof TextboxExt) {
      return selectedObject;
    }

    const textboxes = fabricCanvas?.getObjects().filter((obj): obj is TextboxExt => obj instanceof TextboxExt) ?? [];
    return textboxes.find((obj) => isDefaultText(obj.text)) ?? (textboxes.length === 1 ? textboxes[0] : undefined);
  };

  const activeCsvPlaceholders = (_revision: number) => {
    const target = csvTargetTextbox();
    if (target === undefined) {
      return [];
    }

    return csvTemplateLines(target.text)
      .map((line) => line.match(/^\{\s*(\w+)\s*\}$/)?.[1])
      .filter((placeholder): placeholder is string => placeholder !== undefined);
  };

  const onCsvPlaceholderPicked = (name: string) => {
    const placeholder = `{${name}}`;
    const active = csvTargetTextbox();

    if (active !== undefined) {
      const lines = csvTemplateLines(active.text);
      if (!lines.includes(placeholder) && lines.length >= CSV_MAX_STICKER_ROWS) {
        Toasts.message(`Remove another CSV column first. Stickers can show up to ${CSV_MAX_STICKER_ROWS} rows.`);
        return;
      }

      const nextLines = lines.includes(placeholder)
        ? lines.filter((line) => line !== placeholder)
        : [...lines, placeholder];
      if (nextLines.length > 0) {
        applyCsvTextTemplate(nextLines.join("\n"), active);
      } else {
        active.set({ text: "" });
        fabricCanvas!.setActiveObject(active);
        selectedObject = active;
        selectedCount = 1;
        editRevision++;
        active.setCoords();
        fabricCanvas!.requestRenderAll();
      }
    } else {
      applyCsvTextTemplate(placeholder);
    }

    undo.push(fabricCanvas!, labelProps);
  };

  const onCsvDataLoaded = (placeholders: string[], hasHeader: boolean, replaceCurrentTemplate: boolean = false) => {
    if (placeholders.length === 0) {
      return;
    }

    const target = csvTargetTextbox();
    const nextTemplate = placeholders
      .slice(0, CSV_MAX_STICKER_ROWS)
      .map((placeholder) => `{${placeholder}}`)
      .join("\n");

    if (replaceCurrentTemplate) {
      if (target !== undefined && target.text === nextTemplate) {
        return;
      }

      applyCsvTextTemplate(nextTemplate, target);
      undo.push(fabricCanvas!, labelProps);
      return;
    }

    if (target !== undefined) {
      const validPlaceholders = new Set(placeholders);
      const lines = csvTemplateLines(target.text);
      const nextLines = lines.filter((line) => {
        const placeholderName = line.match(/^\{\s*(\w+)\s*\}$/)?.[1];
        return placeholderName === undefined || validPlaceholders.has(placeholderName);
      });

      if (nextLines.length !== lines.length) {
        applyCsvTextTemplate(nextLines.join("\n"), target);
        undo.push(fabricCanvas!, labelProps);
        return;
      }
    }

    if (hasHeader) {
      return;
    }

    const objects = fabricCanvas!.getObjects();
    const defaultText = objects.length === 1 && objects[0] instanceof TextboxExt ? objects[0] : undefined;
    if (defaultText === undefined || !isDefaultText(defaultText.text)) {
      return;
    }

    const rows = makeCsvColumnAliases(CSV_MAX_STICKER_ROWS).filter((placeholder) => placeholders.includes(placeholder));

    applyCsvTextTemplate(rows.map((placeholder) => `{${placeholder}}`).join("\n"), defaultText);
    undo.push(fabricCanvas!, labelProps);
  };

  const onPaste = async (event: ClipboardEvent) => {
    if (LabelDesignerUtils.isAnyInputFocused(fabricCanvas!)) {
      return;
    }

    const openedDropdowns = document.querySelectorAll(".dropdown-menu.show");
    if (openedDropdowns.length > 0) {
      return;
    }

    if (event.clipboardData != null) {
      event.preventDefault();
      const obj = await LabelDesignerObjectHelper.addObjectFromClipboard(fabricCanvas!, event.clipboardData);

      if (obj !== undefined) {
        fabricCanvas!.setActiveObject(obj);
        undo.push(fabricCanvas!, labelProps);
      }
    }
  };

  const clearCanvas = () => {
    if (!confirm($tr("editor.clear.confirm"))) {
      return;
    }
    undo.push(fabricCanvas!, labelProps);
    fabricCanvas!.clear();
  };

  const loadDefaultLabel = async () => {
    try {
      const urlTemplate = await FileUtils.readLabelFromUrl();

      if (urlTemplate !== null && confirm($tr("params.saved_labels.load.url.warn"))) {
        onLoadRequested(urlTemplate);
        Toasts.message($tr("params.saved_labels.load.url.loaded"));
        return;
      }
    } catch (e) {
      Toasts.error(e);
    }

    try {
      const defaultTemplate = LocalStoragePersistence.loadDefaultTemplate();

      if (defaultTemplate !== null) {
        onLoadRequested(defaultTemplate);
        return;
      }
    } catch (e) {
      Toasts.error(e);
    }

    LabelDesignerObjectHelper.addText(fabricCanvas!, $tr("editor.default_text"));
  };

  const renderOnFontsChanged = () => {
    fabricCanvas?.forEachObject((o) => {
      if (o instanceof fabric.Textbox) {
        o.dirty = true;
      }
    });
    fabricCanvas?.requestRenderAll();
  };

  onMount(async () => {
    try {
      const savedLabelProps = LocalStoragePersistence.loadLastLabelProps();
      if (savedLabelProps !== null) {
        labelProps = savedLabelProps;
      }
    } catch (e) {
      Toasts.zodErrors(e, "Label parameters load error:");
    }

    fabricCanvas = new CustomCanvas(htmlCanvas, {
      width: labelProps.size.width,
      height: labelProps.size.height,
    });
    fabricCanvas.setLabelProps(labelProps);

    await loadDefaultLabel();

    undo.push(fabricCanvas, labelProps);

    // force close dropdowns on touch devices
    fabricCanvas.on("mouse:down", (): void => {
      const dropdowns = document.querySelectorAll("[data-bs-toggle='dropdown']");
      dropdowns.forEach((el) => new Dropdown(el).hide());
    });

    fabricCanvas.on("object:moving", (e): void => {
      if (e.target && e.target.left !== undefined && e.target.top !== undefined) {
        e.target.set({
          left: Math.round(e.target.left / GRID_SIZE) * GRID_SIZE,
          top: Math.round(e.target.top / GRID_SIZE) * GRID_SIZE,
        });
      }
    });

    fabricCanvas.on("object:modified", (): void => {
      undo.push(fabricCanvas!, labelProps);
    });

    fabricCanvas.on("text:changed", () => {
      editRevision++;
    });

    fabricCanvas.on("object:removed", (): void => {
      undo.push(fabricCanvas!, labelProps);
    });

    fabricCanvas.on("selection:created", (e): void => {
      selectedCount = e.selected?.length ?? 0;
      selectedObject = e.selected?.length === 1 ? e.selected[0] : undefined;
      editRevision++;
    });

    fabricCanvas.on("selection:updated", (e): void => {
      selectedCount = e.selected?.length ?? 0;
      selectedObject = e.selected?.length === 1 ? e.selected[0] : undefined;
      editRevision++;
    });

    fabricCanvas.on("selection:cleared", (): void => {
      selectedObject = undefined;
      selectedCount = 0;
      editRevision++;
    });

    fabricCanvas.on("dragover", (e): void => {
      e.e.preventDefault();
    });

    fabricCanvas.on("drop:after", async (e): Promise<void> => {
      const dragEvt = e.e as DragEvent;
      dragEvt.preventDefault();

      let dropped = false;

      if (dragEvt.dataTransfer?.files) {
        for (const file of dragEvt.dataTransfer.files) {
          try {
            await LabelDesignerObjectHelper.addImageFile(fabricCanvas!, file);
            dropped = true;
          } catch (e) {
            Toasts.error(e);
          }
        }

        if (dropped) {
          undo.push(fabricCanvas!, labelProps);
        }
      }
    });

    fabricCanvas.on("object:scaling", (e): void => {
      if (!e.target) {
        return;
      }

      CanvasUtils.fixFabricObjectScale(e.target);
    });

    // userFonts.subscribe((e) => {console.log(e); renderOnFontsChanged();});

    if ($automation !== undefined) {
      if ($automation.startPrint !== undefined) {
        if ($automation.startPrint === "immediately") {
          openPreview();
        } else if ($automation.startPrint === "after_connect") {
          const unsubscribe = connectionState.subscribe((st) => {
            if (st === "connected") {
              tick().then(() => unsubscribe());
              openPreviewAndPrint();
            }
          });
        }
      }
    }
  });

  onDestroy(() => {
    fabricCanvas!.dispose();
  });

  $effect(() => {
    fabricCanvas?.setLabelProps(labelProps);
  });

  $effect(() => {
    if (!previewOpened) {
      printNow = false;
    }
  });

  $effect(() => {
    if ($loadedFonts) {
      renderOnFontsChanged();
    }
  });
</script>

<svelte:window bind:innerWidth={windowWidth} onkeydown={onKeyDown} onpaste={onPaste} />

<div class="image-editor">
  <div class="row mb-3">
    <div class="col d-flex {windowWidth === 0 || labelProps.size.width < windowWidth ? 'justify-content-center' : ''}">
      <div class="canvas-wrapper print-start-{labelProps.printDirection}">
        <canvas bind:this={htmlCanvas}></canvas>
      </div>
    </div>
  </div>

  <div class="row mb-1">
    <div class="col d-flex justify-content-center">
      <div class="toolbar d-flex flex-wrap gap-1 justify-content-center align-items-center">
        <LabelPropsEditor {labelProps} onChange={onUpdateLabelProps} />

        <button class="btn btn-sm btn-secondary" onclick={clearCanvas} title={$tr("editor.clear")}>
          <MdIcon icon="cancel_presentation" />
        </button>

        <SavedLabelsMenu
          canvas={fabricCanvas!}
          onRequestLabelTemplate={exportCurrentLabel}
          {onLoadRequested}
          {csvEnabled} />

        <button
          class="btn btn-sm btn-secondary"
          disabled={undoState.undoDisabled}
          onclick={() => undo.undo()}
          title={$tr("editor.undo")}>
          <MdIcon icon="undo" />
        </button>

        <button
          class="btn btn-sm btn-secondary"
          disabled={undoState.redoDisabled}
          onclick={() => undo.redo()}
          title={$tr("editor.redo")}>
          <MdIcon icon="redo" />
        </button>

        <CsvControl
          bind:enabled={csvEnabled}
          onPlaceholderPicked={onCsvPlaceholderPicked}
          onDataLoaded={onCsvDataLoaded}
          activePlaceholders={activeCsvPlaceholders(editRevision)}
          maxActivePlaceholders={CSV_MAX_STICKER_ROWS} />

        <IconPicker onSubmit={onIconPicked} onSubmitSvg={onSvgIconPicked} />
        <ObjectPicker onSubmit={onObjectPicked} {labelProps} {zplImageReady} />

        <button class="btn btn-sm btn-primary ms-1" onclick={openPreview}>
          <MdIcon icon="visibility" />
          {$tr("editor.preview")}
        </button>
        <button
          title="Print with default or saved parameters"
          class="btn btn-sm btn-primary ms-1"
          onclick={openPreviewAndPrint}
          disabled={$connectionState !== "connected"}><MdIcon icon="print" /> {$tr("editor.print")}</button>
      </div>
    </div>
  </div>

  <div class="row mb-1">
    <div class="col d-flex justify-content-center">
      <div class="toolbar d-flex flex-wrap gap-1 justify-content-center align-items-center">
        {#if selectedCount > 0}
          <button class="btn btn-sm btn-danger me-1" onclick={deleteSelected} title={$tr("editor.delete")}>
            <MdIcon icon="delete" />
          </button>
        {/if}

        {#if selectedCount > 0}
          <button class="btn btn-sm btn-secondary me-1" onclick={cloneSelected} title={$tr("editor.clone")}>
            <MdIcon icon="content_copy" />
          </button>
        {/if}

        {#if selectedObject && selectedCount === 1}
          <GenericObjectParamsControls {selectedObject} {editRevision} valueUpdated={controlValueUpdated} />
        {/if}

        {#if selectedObject}
          <VectorParamsControls {selectedObject} {editRevision} valueUpdated={controlValueUpdated} />
        {/if}

        {#if selectedObject instanceof fabric.IText}
          <TextParamsControls selectedText={selectedObject} {editRevision} valueUpdated={controlValueUpdated} />
        {/if}

        {#if selectedObject instanceof QRCode}
          <QrCodeParamsPanel selectedQRCode={selectedObject} {editRevision} valueUpdated={controlValueUpdated} />
        {/if}

        {#if selectedObject instanceof Barcode}
          <BarcodeParamsPanel selectedBarcode={selectedObject} {editRevision} valueUpdated={controlValueUpdated} />
        {/if}

        {#if selectedObject instanceof fabric.IText || selectedObject instanceof QRCode || (selectedObject instanceof Barcode && selectedObject.encoding === "CODE128B")}
          <VariableInsertControl {selectedObject} valueUpdated={controlValueUpdated} />
        {/if}
      </div>
    </div>
  </div>

  {#if previewOpened}
    <PrintPreview
      bind:show={previewOpened}
      canvasCallback={getCanvasForPreview}
      {labelProps}
      {printNow}
      {csvEnabled}
      csvData={$csvData.data}
      csvDelimiter={$csvData.delimiter}
      csvHasHeader={$csvData.hasHeader}
      csvOneItemPerCell={$csvData.oneItemPerCell} />
  {/if}
</div>

<style>
  .canvas-wrapper {
    border: 1px solid var(--border-standard);
    background-color: var(--surface-1);
  }
  .canvas-wrapper.print-start-left {
    border-left: 2px solid var(--mark-feed);
  }
  .canvas-wrapper.print-start-top {
    border-top: 2px solid var(--mark-feed);
  }
  .canvas-wrapper canvas {
    image-rendering: pixelated;
  }
</style>
