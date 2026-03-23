<script lang="ts">
  import { Utils } from "$/lib/fichero";
  import { tr } from "$/utils/i18n";
  import MdIcon from "$/components/basic/MdIcon.svelte";
  import { detectAntiFingerprinting, detectChromeBased } from "$/utils/browsers";
  let caps = Utils.getAvailableTransports();

  let antiFingerprinting = detectAntiFingerprinting();
  let isChromeBased = detectChromeBased();
  let isMobile = typeof navigator !== "undefined" && /iPhone|iPad|iPod|Android/i.test(navigator.userAgent);
</script>

{#if !caps.webBluetooth}
  <div class="alert alert-danger text-center" role="alert">
    {#if isMobile}
      <MdIcon icon="computer" />
      Open on a desktop browser (Chrome, Edge, or Opera) to connect to your printer.
    {:else}
      <div>
        {$tr("browser_warning.lines.first")}
      </div>
      {#if isChromeBased}
        <div style="margin-top: 10px; font-size: 0.9em;">
          {$tr("browser_warning.lines.third")}
        </div>
      {/if}
      <div>
        {$tr("browser_warning.lines.second")}
      </div>
    {/if}
  </div>
{/if}

{#if antiFingerprinting}
  <div class="alert alert-danger" role="alert">
    {$tr("browser_warning.fingerprinting")}
  </div>
{/if}

<style>
</style>
