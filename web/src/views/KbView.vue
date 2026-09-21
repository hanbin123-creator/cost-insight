<template>
  <!-- F10 知识库（选型 V4 检索优先 RAG 透明化 + V1 文档列表管理）：
       检索三路召回/RRF/精排全部后端完成，命中块连通道与分数原样展示，前端不算分 -->
  <div class="kb">
    <!-- 检索优先：顶部大搜索框 -->
    <section class="panel search-bar">
      <div class="search-row">
        <input v-model="q" placeholder="检索知识库：如「金银花涨价」「设备故障率」…"
          @keyup.enter="search" />
        <button class="search-btn" :disabled="searching || !q.trim()" @click="search">
          {{ searching ? '检索中…' : '检索' }}
        </button>
      </div>
      <p class="search-hint">三路召回（向量 / 关键词 / 图谱）→ RRF 融合 → 规则精排；每个命中标注来源通道与出处</p>
    </section>

    <p v-if="searchErr" class="err-line">⚠ {{ searchErr }}</p>

    <!-- 命中结果（透明化：通道 chips + RRF 分 + 出处） -->
    <section v-if="result" class="panel hits">
      <h3>检索结果<span class="count">{{ result.hits.length }}</span></h3>
      <div v-if="!result.hits.length" class="state">无命中——换个说法或先上传相关文档</div>
      <article v-for="h in result.hits" :key="h.chunk_id" class="hit">
        <div class="h-head">
          <strong class="h-doc">{{ h.doc_name }}</strong>
          <span class="h-loc">第 {{ h.page ?? '—' }} 页 · {{ h.section ?? '—' }}</span>
          <span class="h-type">{{ h.doc_type }}</span>
        </div>
        <p class="h-text">{{ snippet(h.text) }}</p>
        <div class="h-meta">
          <span v-for="c in h.channels" :key="c" class="ch-chip">{{ channelLabel(c) }}</span>
          <span class="h-score">RRF {{ h.rrf_score.toFixed(4) }}</span>
        </div>
      </article>
    </section>

    <!-- 文档管理 -->
    <section class="panel docs">
      <div class="docs-head">
        <h3>文档管理<span class="count">{{ docs?.documents.length ?? 0 }}</span></h3>
        <div class="docs-actions">
          <span class="job" :class="docs?.job.state">{{ jobStateText(docs?.job ?? { state: 'idle' }) }}</span>
          <label class="upload-btn" :class="{ disabled: busy }">
            上传文档
            <input type="file" accept=".txt,.md,.pdf,.docx" :disabled="busy" @change="upload" hidden />
          </label>
          <button class="refresh-btn" :disabled="busy" @click="refreshDocs">刷新</button>
        </div>
      </div>
      <p v-if="docNote" class="doc-note" :class="{ err: docErr }">{{ docNote }}</p>
      <div v-if="docsLoading" class="state">加载中…</div>
      <table v-else-if="docs?.documents.length" class="doc-table">
        <thead>
          <tr><th>文档</th><th>大小</th><th>索引块</th><th>版本</th><th>状态</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="d in docs.documents" :key="d.name">
            <td class="d-name">{{ d.name }}</td>
            <td>{{ fmtSize(d.size_kb) }}</td>
            <td>{{ d.indexed ? d.indexed_chunks : '—' }}</td>
            <td class="d-ver">{{ d.doc_version ?? '—' }}</td>
            <td>
              <span class="idx" :class="{ ok: d.indexed }">{{ d.indexed ? '已索引' : '未索引' }}</span>
            </td>
            <td>
              <button class="del" :disabled="busy" @click="remove(d.name)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else class="state">暂无文档</div>
      <p class="total" v-if="docs">全库索引块总数：{{ docs.total_chunks }}</p>
    </section>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
import { channelLabel, fmtSize, jobStateText, snippet } from '../archiveHelpers'
import type { KbDocsResp, KbQueryResp } from '../types'

const q = ref('')
const searching = ref(false)
const searchErr = ref('')
const result = ref<KbQueryResp | null>(null)

const docs = ref<KbDocsResp | null>(null)
const docsLoading = ref(false)
const busy = ref(false)
const docNote = ref('')
const docErr = ref(false)

async function search() {
  const query = q.value.trim()
  if (!query || searching.value) return
  searching.value = true
  searchErr.value = ''
  try { result.value = await api.kbQuery(query) }
  catch (e) { result.value = null; searchErr.value = e instanceof Error ? e.message : String(e) }
  finally { searching.value = false }
}

async function refreshDocs() {
  docsLoading.value = true
  try { docs.value = await api.kbDocs() }
  catch (e) { docNote.value = `文档清单加载失败：${e instanceof Error ? e.message : String(e)}`; docErr.value = true }
  finally { docsLoading.value = false }
}

async function upload(ev: Event) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''   // 允许同名文件再次选择
  if (!file || busy.value) return
  busy.value = true
  docErr.value = false
  docNote.value = ''
  try {
    const buf = await file.arrayBuffer()
    // base64 编码（分块防栈溢出：大文件逐块转字符串）
    const bytes = new Uint8Array(buf)
    let bin = ''
    for (let i = 0; i < bytes.length; i += 0x8000) {
      bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000))
    }
    const r = await api.kbUpload(file.name, btoa(bin))
    docNote.value = `已受理：${r.filename}（${r.note}）`
    // 后台重建中：轮询两次让状态尽快可见，最终态由用户刷新确认
    await refreshDocs()
    setTimeout(refreshDocs, 3000)
  } catch (e) {
    docNote.value = `上传失败：${e instanceof Error ? e.message : String(e)}`
    docErr.value = true
  } finally {
    busy.value = false
  }
}

async function remove(name: string) {
  if (busy.value) return
  busy.value = true
  docErr.value = false
  try {
    await api.kbDelete(name)
    docNote.value = `已删除：${name}（索引后台重建中）`
    await refreshDocs()
    setTimeout(refreshDocs, 3000)
  } catch (e) {
    docNote.value = `删除失败：${e instanceof Error ? e.message : String(e)}`
    docErr.value = true
  } finally {
    busy.value = false
  }
}

onMounted(refreshDocs)
</script>

<style scoped>
.kb { display: flex; flex-direction: column; gap: 14px; }
.panel { background: var(--card); border-radius: var(--radius); box-shadow: var(--shadow); padding: 14px 18px; }

.search-row { display: flex; gap: 10px; }
.search-row input {
  flex: 1; border: none; border-radius: 10px; padding: 11px 14px; font-size: 13.5px;
  background: rgba(93, 109, 126, 0.08); outline: none;
}
.search-btn {
  border: none; border-radius: 10px; padding: 11px 22px; cursor: pointer;
  background: var(--primary); color: #fff; font-size: 13px;
  box-shadow: 0 3px 10px rgba(46, 109, 164, 0.3);
}
.search-btn:disabled { opacity: 0.6; cursor: wait; }
.search-hint { margin: 8px 0 0; font-size: 11px; color: var(--text-label); }
.err-line { margin: 0; font-size: 12.5px; color: var(--sem-alert); }

.hits h3, .docs h3 { margin: 0; font-size: 13px; font-weight: 600; color: var(--text-unit); }
.count {
  margin-left: 8px; font-size: 11px; color: var(--text-label);
  background: rgba(93, 109, 126, 0.1); border-radius: 999px; padding: 1px 8px;
}
.hit { padding: 10px 0; border-bottom: 1px solid #eef1f6; }
.hit:last-child { border-bottom: none; }
.h-head { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.h-doc { font-size: 12.5px; color: var(--text-num); }
.h-loc, .h-type { font-size: 11px; color: var(--text-label); }
.h-type { padding: 0 6px; border-radius: 6px; background: rgba(93, 109, 126, 0.08); }
.h-text { margin: 6px 0; font-size: 12.5px; color: var(--text-num); line-height: 1.6; }
.h-meta { display: flex; align-items: center; gap: 6px; }
.ch-chip {
  font-size: 10.5px; padding: 1px 7px; border-radius: 999px;
  background: rgba(46, 109, 164, 0.1); color: var(--primary);
}
.h-score { margin-left: auto; font-size: 10.5px; color: var(--text-label); font-variant-numeric: tabular-nums; }

.docs-head { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; margin-bottom: 10px; }
.docs-actions { display: flex; align-items: center; gap: 10px; }
.job { font-size: 11px; color: var(--text-label); }
.job.running { color: #b9770e; }
.job.failed { color: #c0392b; }
.upload-btn {
  border-radius: 10px; padding: 8px 14px; cursor: pointer; font-size: 12.5px;
  background: var(--primary); color: #fff;
}
.upload-btn.disabled { opacity: 0.6; cursor: wait; }
.refresh-btn {
  border: none; border-radius: 10px; padding: 8px 14px; cursor: pointer;
  background: rgba(93, 109, 126, 0.1); color: var(--text-unit); font-size: 12.5px;
}
.doc-note { margin: 0 0 8px; font-size: 12.5px; color: #1e8449; }
.doc-note.err { color: #c0392b; }
.doc-table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.doc-table th {
  text-align: left; font-weight: 600; font-size: 11px; color: var(--text-label);
  padding: 6px 8px; border-bottom: 1px solid #eef1f6;
}
.doc-table td { padding: 8px; border-bottom: 1px solid #f4f6fa; color: var(--text-num); }
.d-name { max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.d-ver { font-size: 11px; color: var(--text-label); }
.idx { font-size: 11px; color: var(--text-label); }
.idx.ok { color: #1e8449; }
.del { border: none; background: none; cursor: pointer; color: #c0392b; font-size: 12px; }
.del:disabled { opacity: 0.5; cursor: wait; }
.total { margin: 10px 0 0; font-size: 11px; color: var(--text-label); }
.state { min-height: 80px; display: flex; align-items: center; justify-content: center; color: var(--text-label); }
</style>
