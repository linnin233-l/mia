<template>
  <div>
    <h3>Agent 模型分配</h3>
    <p style="font-size: 12px; color: #909399; margin: 0 0 12px">从 RuntimeConfig 加载，修改即时生效。下拉框仅显示具备所需能力的模型。</p>
    <div v-if="loading" style="color: #909399; padding: 20px">加载配置中...</div>
    <el-table v-else :data="agentRows" stripe>
      <el-table-column label="Agent" width="130">
        <template #default="{ row }">{{ row.label }}</template>
      </el-table-column>
      <el-table-column label="主模型" width="230">
        <template #default="{ row }">
          <div v-if="row.hasModel">
            <el-select
              :model-value="getModel(row.key)"
              size="small"
              style="width: 190px"
              @change="(val: string) => handleSave(row.key, 'model', val)"
            >
              <el-option
                v-for="m in getModelOptions(row.key)"
                :key="m.id"
                :label="m.label"
                :value="m.id"
                :disabled="m.conflict"
              />
            </el-select>
            <div v-if="modelConflict(row.key)" style="color: #f56c6c; font-size: 11px; margin-top: 2px">
              冲突: {{ modelConflict(row.key) }}
            </div>
          </div>
          <span v-else style="color: #909399">-</span>
        </template>
      </el-table-column>
      <el-table-column label="备选" width="230">
        <template #default="{ row }">
          <div v-if="row.hasFallback">
            <el-select
              :model-value="getFallback(row.key)"
              size="small"
              style="width: 190px"
              clearable
              placeholder="无"
              @change="(val: string) => handleSave(row.key, 'fallback', val || '')"
            >
              <el-option
                v-for="m in getModelOptions(row.key)"
                :key="m.id"
                :label="m.label"
                :value="m.id"
                :disabled="m.conflict"
              />
            </el-select>
          </div>
          <span v-else style="color: #909399">-</span>
        </template>
      </el-table-column>
      <el-table-column label="功能" min-width="200">
        <template #default="{ row }">
          <template v-if="row.key === 'receiver'">
            <div style="display: flex; flex-direction: column; gap: 4px">
              <el-switch
                :model-value="cfg.receiver?.vision_enabled"
                size="small"
                active-text="视觉"
                @change="(val: boolean) => handleSave('receiver', 'vision_enabled', val)"
              />
              <el-switch
                :model-value="cfg.receiver?.audio_enabled"
                size="small"
                active-text="语音"
                @change="(val: boolean) => handleSave('receiver', 'audio_enabled', val)"
              />
            </div>
          </template>
          <template v-else-if="row.key === 'sender'">
            <el-switch
              :model-value="cfg.sender?.tts_enabled"
              size="small"
              active-text="语音合成"
              @change="(val: boolean) => handleSave('sender', 'tts_enabled', val)"
            />
          </template>
          <span v-else style="color: #909399; font-size: 12px">-</span>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { getModels, updateAgentConfig, getAgentCapabilities } from '@/api/config'
import client from '@/api/client'

const loading = ref(true)
const cfg = ref<any>({})
const allModels = ref<any[]>([])
const capabilities = ref<Record<string, any>>({})

const keyMap: Record<string, string> = { scheduler: 'scheduler', task: 'task', memory: 'memory' }

const agentRows = [
  { key: 'scheduler', label: 'Scheduler', hasModel: true, hasFallback: true },
  { key: 'task', label: 'TaskAgent', hasModel: true, hasFallback: true },
  { key: 'memory', label: 'MemoryAgent', hasModel: true, hasFallback: true },
  { key: 'receiver', label: 'Receiver', hasModel: true, hasFallback: false },
  { key: 'sender', label: 'Sender', hasModel: true, hasFallback: false },
]

// Agent 角色 → 能力要求
const agentCaps: Record<string, { primary: string[] }> = {
  scheduler: { primary: ['text_chat'] },
  task: { primary: ['text_chat'] },
  memory: { primary: ['text_chat'] },
  receiver: { primary: ['text_chat'] },
  sender: { primary: ['tts'] },
}

onMounted(async () => {
  try {
    const [configRes, modelsRes, capsRes] = await Promise.all([
      client.get('/config'),
      getModels(),
      getAgentCapabilities(),
    ])
    cfg.value = configRes.data
    allModels.value = modelsRes.models
    capabilities.value = capsRes
  } catch {}
  loading.value = false
})

function getModel(key: string): string {
  if (key in keyMap) return cfg.value[keyMap[key]]?.model || ''
  if (key === 'receiver') return cfg.value.receiver?.text_model || ''
  if (key === 'sender') return cfg.value.sender?.tts_model || ''
  return ''
}

function getFallback(key: string): string {
  if (key in keyMap) return cfg.value[keyMap[key]]?.fallback || ''
  return ''
}

// 模型是否具备指定能力集合
function hasCaps(modelId: string, required: string[]): boolean {
  const m = allModels.value.find((x: any) => x.id === modelId)
  if (!m) return false
  return required.every((c: string) => m.capabilities.includes(c))
}

// 获取当前角色的能力要求
function getRequiredCaps(key: string): string[] {
  return agentCaps[key]?.primary || ['text_chat']
}

// 下拉框选项：只显示具备所需能力的模型
function getModelOptions(key: string): { id: string; label: string; conflict: boolean }[] {
  const required = getRequiredCaps(key)
  const current = getModel(key)
  const fb = getFallback(key)

  return allModels.value
    .filter((m: any) => m.enabled)
    .map((m: any) => {
      const ok = required.every((c: string) => m.capabilities.includes(c))
      return { id: m.id, label: m.id, conflict: !ok }
    })
}

// 当前模型是否与能力要求冲突
function modelConflict(key: string): string {
  const model = getModel(key)
  if (!model) return ''
  const required = getRequiredCaps(key)
  const m = allModels.value.find((x: any) => x.id === model)
  if (!m) return ''
  const missing = required.filter((c: string) => !m.capabilities.includes(c))
  if (missing.length === 0) return ''
  return `模型缺少: ${missing.join(', ')}`
}

async function handleSave(agentKey: string, field: string, value: any) {
  // 前端预校验
  if (field === 'model' && value) {
    const required = getRequiredCaps(agentKey)
    if (!hasCaps(value, required)) {
      return // 不发送请求
    }
  }

  const body: Record<string, any> = {}
  if (field === 'model') body.model = value
  else if (field === 'fallback') body.fallback = value
  else body[field] = value

  try {
    await updateAgentConfig(agentKey, body)
    const agentCfgKey = keyMap[agentKey] || agentKey
    if (field === 'model') {
      if (agentKey === 'sender') cfg.value.sender.tts_model = value
      else if (agentKey === 'receiver') cfg.value.receiver.text_model = value
      else if (cfg.value[agentCfgKey]) cfg.value[agentCfgKey].model = value
    } else if (field === 'fallback') {
      if (cfg.value[agentCfgKey]) cfg.value[agentCfgKey].fallback = value
    } else {
      if (agentKey === 'receiver' && cfg.value.receiver) (cfg.value.receiver as any)[field] = value
      if (agentKey === 'sender' && cfg.value.sender) (cfg.value.sender as any)[field] = value
    }
  } catch (e: any) {
    // 后端校验失败
    const errMsg = e?.response?.data?.error || ''
    if (errMsg) {
      // 用浏览器 alert 提示（简单直接）
      alert(`配置冲突: ${errMsg}`)
    }
  }
}
</script>
