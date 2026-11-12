<script setup lang="ts">
import { ui, closeDialog, closeCtx, closeLightbox } from '../useUi'
</script>

<template>
  <div id="intro-toasts">
    <div v-for="t in ui.toasts" :key="t.id" class="intro-toast" :class="t.kind">
      <span>{{ t.msg }}</span>
      <button v-if="t.act" @click="t.act.fn(); ui.toasts = ui.toasts.filter(x => x.id !== t.id)">{{ t.act.label }}</button>
    </div>
  </div>
  <div v-if="ui.dialog" class="intro-dialog" @click.self="closeDialog">
    <div class="dlg">
      <h4>{{ ui.dialog.title }}</h4>
      <div class="dlg-body" v-html="ui.dialog.body"></div>
      <div class="dlg-nav">
        <button v-for="(b, i) in ui.dialog.buttons" :key="i" class="m-btn" :class="b.cls"
          @click="closeDialog(); b.fn && b.fn()">{{ b.label }}</button>
      </div>
    </div>
  </div>
  <div v-if="ui.ctx" class="intro-ctx" :style="{ left: ui.ctx.x + 'px', top: ui.ctx.y + 'px' }">
    <template v-for="(it, i) in ui.ctx.items" :key="i">
      <div v-if="it.sep" style="height:1px;background:var(--vp-c-border);margin:4px 6px"></div>
      <button v-else @click="closeCtx(); it.fn && it.fn()">{{ it.label }}</button>
    </template>
  </div>
  <div v-if="ui.lightbox" class="intro-lightbox" @click.self="closeLightbox">
    <img :src="ui.lightbox.src" alt="截图放大" @click.stop>
    <div class="lb-cap">{{ ui.lightbox.cap }}</div>
  </div>
</template>