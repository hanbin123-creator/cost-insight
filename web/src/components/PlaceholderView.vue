<template>
  <!-- 占位视图：确定性空态（条款 8）——说明该页将落地的已选方案，不是空白 -->
  <div class="placeholder-card">
    <h2>{{ title }}</h2>
    <p class="plan">已选方案：{{ plan }}</p>
    <p class="hint">{{ hint }}</p>
  </div>
</template>

<script setup lang="ts">
defineProps<{ title: string; plan: string; hint: string }>()
</script>

<style scoped>
.placeholder-card {
  background: var(--card); border: 1.5px dashed var(--border); border-radius: var(--radius);
  box-shadow: var(--shadow); padding: 60px 40px; text-align: center;
}
h2 { font-size: 18px; margin: 0 0 10px; }
.plan { color: var(--primary); font-size: 13px; margin: 0 0 6px; }
.hint { color: var(--text-unit); font-size: 12px; margin: 0; }
</style>
