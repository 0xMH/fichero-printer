<script lang="ts">
  import BrowserWarning from "$/components/basic/BrowserWarning.svelte";
  import LabelDesigner from "$/components/LabelDesigner.svelte";
  import PrinterConnector from "$/components/PrinterConnector.svelte";
  import { locale, locales, tr } from "$/utils/i18n";
  import DebugStuff from "$/components/DebugStuff.svelte";
  import MdIcon from "$/components/basic/MdIcon.svelte";

  // eslint-disable-next-line no-undef
  const appCommit = __APP_COMMIT__;
  // eslint-disable-next-line no-undef
  const buildDate = __BUILD_DATE__;

  let debugStuffShow = $state<boolean>(false);
</script>

<div class="container my-2">
  <div class="row align-items-center mb-3">
    <div class="col">
      <h1 class="title">
        <img src="{import.meta.env.BASE_URL}logo.png" alt="Fichero" class="logo" />
      </h1>
    </div>
    <div class="col-md-3">
      <PrinterConnector />
    </div>
  </div>
  <div class="row">
    <div class="col">
      <BrowserWarning />
    </div>
  </div>

  <div class="row">
    <div class="col">
      <LabelDesigner />
    </div>
  </div>
</div>

<div class="footer text-end text-secondary p-3">
  <div>
    <select class="form-select form-select-sm text-secondary d-inline-block w-auto" bind:value={$locale}>
      {#each Object.entries(locales) as [key, name] (key)}
        <option value={key}>{name}</option>
      {/each}
    </select>
  </div>
  <div>
    {#if appCommit}
      <a class="text-secondary" href="https://github.com/mohamedha/fichero-printer/commit/{appCommit}">
        {appCommit.slice(0, 6)}
      </a>
    {/if}
    {$tr("main.built")}
    {buildDate}
  </div>
  <div>
    <a class="text-secondary" href="https://github.com/mohamedha/fichero-printer">{$tr("main.code")}</a>
    <button class="text-secondary btn btn-link p-0" onclick={() => debugStuffShow = true}>
      <MdIcon icon="bug_report" />
    </button>
  </div>
</div>

{#if debugStuffShow}
  <DebugStuff bind:show={debugStuffShow} />
{/if}

<style>
  .logo {
    height: 1.4em;
    vertical-align: middle;
    margin-right: 0.2em;
    border-radius: 4px;
  }

  .footer {
    position: absolute;
    bottom: 0;
    right: 0;
    z-index: -1;
  }

  @media only screen and (max-device-width: 540px) {
    .footer {
      position: relative !important;
      z-index: 0 !important;
    }
  }
</style>
