<script setup lang="ts">
import { ref, computed } from 'vue'
import { withBase } from 'vitepress'
import { SHOTS } from '../data'
import { openLightbox } from '../useUi'
const props = defineProps<{ k: string }>()
const shot = computed(() => SHOTS[props.k])
const open = ref(-1)
function bubbleStyle(h: { x: number; y: number }) {
  return {
    left: h.x + '%', top: h.y + '%',
    '--tx': h.x < 18 ? '-6%' : h.x > 82 ? '-94%' : '-50%',
  }
}
</script>

<template>
  <figure class="shot">
    <div class="shot-frame">
      <img :src="withBase(shot.src)" :width="shot.w" :height="shot.h" :alt="shot.cap"
        @click="openLightbox(withBase(shot.src), shot.cap)">
      <button v-for="(h, i) in shot.hs" :key="i" class="hs" :class="{ on: open === i }"
        :style="{ '--x': h.x + '%', '--y': h.y + '%' }" :aria-label="'标注 ' + (i + 1) + '：' + h.t"
        @click.stop="open = open === i ? -1 : i">{{ i + 1 }}</button>
      <div v-if="open >= 0" class="hs-bubble" :class="shot.hs[open].y < 24 ? 'below' : 'above'" :style="bubbleStyle(shot.hs[open])">
        <b>{{ open + 1 }} · {{ shot.hs[open].t }}</b>{{ shot.hs[open].d }}
      </div>
    </div>
    <figcaption>{{ shot.cap }}<span style="opacity:.85">点击编号圆点看标注 · 点击图片放大</span></figcaption>
    <ol v-if="shot.hs.length" class="shot-notes">
      <li v-for="(h, i) in shot.hs" :key="i" :class="{ on: open === i }" @click="open = open === i ? -1 : i">
        <span class="n">{{ i + 1 }}</span><span><b>{{ h.t }}</b> — {{ h.d }}</span>
      </li>
    </ol>
  </figure>
</template>