<template>
  <div>
    <h3>Agent 模型分配</h3>
    <p style="font-size: 12px; color: #909399; margin: 0 0 12px">从 RuntimeConfig 加载，修改即时生效。</p>
    <div v-if="loading" style="color: #909399; padding: 20px">加载配置中...</div>
    <el-table v-else :data="agentRows" stripe>
      <el-table-column label="Agent" width="130">
        <template #default="{ row }">{{ row.label }}</template>
      </el-table-column>
      <el-table-column label="主模型" width="210">
        <template #default="{ row }">
          <el-select
            v-if="row.hasModel"
            :model-value="getModel(row.key)"
            size="small"
            style="width: 190px"
            @change="(val: string) => handleSave(row.key, 'model', val)"
          >
            <el-option
              v-for="m in getModelOptions(row.key)"
              :key="m"
              :label="m"
              :value="m"
            />
          </el-select>
          <span v-else style="color: #909399">-</span>
        </template>
      </el-table-column>
      <el-table-column label="备选" width="210">
        <template #default="{ row }">
          <el-select
            v-if="row.hasFallback"
            :model-value="getFallback(row.key)"
            size="small"
            style="width: 190px"
            clearable
            placeholder="无"
            @change="(val: string) => handleSave(row.key, 'fallback', val || '')"
          >
            <el-option
              v-for="m in getModelOptions(row.key)"
              :key="m"
              :label="m"
              :value="m"
            />
          </el-select>
          <span v-else style="color: #909399">-</span>
        </template>
      </el-table-column>
      <el-table-column label="功能" min-width="180">
        <template #default="{ row }">
          <template v-if="row.key === 'receiver'">
            <el-switch
              :model-value="cfg.receiver?.vision_enabled"
              size="small"
              active-text="视觉"
              style="margin-right: 8px"
              @change="(val: boolean) => handleSave('receiver', 'vision_enabled', val)"
            />
            <el-switch
              :model-value="cfg.receiver?.audio_enabled"
              size="small"
              active-text="语音"
              @change="(val: boolean) => handleSave('receiver', 'audio_enabled', val)"
            />
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
import { getModels, updateAgentConfig } from '@/api/config'
import client from '@/api/client'

const loading = ref(true)
const cfg = ref<any>({})
const allModels = ref<any[]>([])
const textModels = ref<string[]>([])

const agentRows = [
  { key: 'scheduler', label: 'Scheduler', hasModel: true, hasFallback: true },
  { key: 'task', label: 'TaskAgent', hasModel: true, hasFallback: true },
  { key: 'memory', label: 'MemoryAgent', hasModel: true, hasFallback: true },
  { key: 'receiver', label: 'Receiver', hasModel: true, hasFallback: false },
  { key: 'sender', label: 'Sender', hasModel: true, hasFallback: false },
]

onMounted(async () => {
  try {
    const [configRes, modelsRes] = await Promise.all([
      client.get('/config'),
      getModels(),
    ])
    cfg.value = configRes.data
    allModels.value = modelsRes.models
    textModels.value = modelsRes.models
      .filter((m: any) => m.enabled && m.capabilities.includes('text_chat'))
      .map((m: any) => m.id)
  } catch {}
  loading.value = false
})

// Model getters from current RuntimeConfig
const keyMap: Record<string, string> = {
  scheduler: 'scheduler', task: 'task', memory: 'memory',
}

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

// Dropdown options: always include currently configured model + available text models
function getModelOptions(key: string): string[] {
  const current = getModel(key)
  const fb = getFallback(key)
  const opts = new Set(textModels.value)
  if (current) opts.add(current)
  if (fb) opts.add(fb)
  return Array.from(opts).sort()
}

async function handleSave(agentKey: string, field: string, value: any) {
  const body: Record<string, any> = {}
  if (field === 'model') body.model = value
  else if (field === 'fallback') body.fallback = value
  else body[field] = value

  try {
    await updateAgentConfig(agentKey, body)
    // Update local cfg immediately so UI reflects change
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
  } catch {}
}
</script>
