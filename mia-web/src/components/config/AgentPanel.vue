<template>
  <div>
    <h3>Agent 模型分配</h3>
    <p style="font-size: 12px; color: #909399; margin: 0 0 12px">
      下拉框根据所需能力过滤。功能关闭时能力要求放宽。
    </p>
    <div v-if="loading" style="color: #909399; padding: 20px">加载配置中...</div>
    <div v-else style="display: flex; flex-direction: column; gap: 16px">

      <!-- Scheduler / TaskAgent / MemoryAgent -->
      <el-card v-for="row in textAgents" :key="row.key" shadow="never">
        <template #header>
          <span style="font-weight: 500">{{ row.label }}</span>
          <span style="font-size: 12px; color: #909399; margin-left: 8px">需要: text_chat</span>
        </template>
        <div style="display: flex; gap: 24px; align-items: center; flex-wrap: wrap">
          <div>
            <span style="font-size: 13px; color: #606266; margin-right: 8px">主模型</span>
            <ModelSelect :model-value="getTextModel(row.key)" :models="textModels" required-caps="text_chat"
              @change="(v: string) => handleSave(row.key, 'model', v)" />
          </div>
          <div>
            <span style="font-size: 13px; color: #606266; margin-right: 8px">备选</span>
            <ModelSelect :model-value="getTextFallback(row.key)" :models="textModels" required-caps="text_chat"
              clearable @change="(v: string) => handleSave(row.key, 'fallback', v || '')" />
          </div>
        </div>
      </el-card>

      <!-- Receiver -->
      <el-card shadow="never">
        <template #header>
          <span style="font-weight: 500">Receiver</span>
          <span style="font-size: 12px; color: #909399; margin-left: 8px">需要: text_chat (文本), vision (视觉), audio_understanding (语音)</span>
        </template>
        <div style="display: flex; flex-direction: column; gap: 12px">
          <div style="display: flex; gap: 24px; align-items: center; flex-wrap: wrap">
            <div>
              <span style="font-size: 13px; color: #606266; margin-right: 8px">文本模型</span>
              <ModelSelect :model-value="cfg.receiver?.text_model || ''" :models="textModels" required-caps="text_chat"
                @change="(v: string) => handleSave('receiver', 'model', v)" />
            </div>
            <div style="display: flex; gap: 12px; align-items: center">
              <el-switch :model-value="cfg.receiver?.vision_enabled" size="small" active-text="视觉"
                @change="(v: boolean) => handleSave('receiver', 'vision_enabled', v)" />
              <div v-if="cfg.receiver?.vision_enabled">
                <ModelSelect :model-value="cfg.receiver?.vision_model || cfg.receiver?.text_model || ''"
                  :models="visionModels" required-caps="vision" @change="(v: string) => handleSave('receiver', 'vision_model', v)" />
              </div>
            </div>
            <div style="display: flex; gap: 12px; align-items: center">
              <el-switch :model-value="cfg.receiver?.audio_enabled" size="small" active-text="语音"
                @change="(v: boolean) => handleSave('receiver', 'audio_enabled', v)" />
              <div v-if="cfg.receiver?.audio_enabled">
                <ModelSelect :model-value="cfg.receiver?.audio_model || cfg.receiver?.text_model || ''"
                  :models="audioModels" required-caps="audio_understanding"
                  @change="(v: string) => handleSave('receiver', 'audio_model', v)" />
              </div>
            </div>
          </div>
          <div v-if="receiverConflict" style="color: #f56c6c; font-size: 12px">
            冲突: {{ receiverConflict }}
          </div>
        </div>
      </el-card>

      <!-- Sender -->
      <el-card shadow="never">
        <template #header>
          <span style="font-weight: 500">Sender</span>
          <span style="font-size: 12px; color: #909399; margin-left: 8px">
            {{ cfg.sender?.tts_enabled ? '需要: tts' : '需要: text_chat (语音合成已关闭)' }}
          </span>
        </template>
        <div style="display: flex; gap: 24px; align-items: center; flex-wrap: wrap">
          <div style="display: flex; gap: 12px; align-items: center">
            <el-switch :model-value="cfg.sender?.tts_enabled" size="small" active-text="语音合成"
              @change="(v: boolean) => handleSave('sender', 'tts_enabled', v)" />
          </div>
          <div>
            <span style="font-size: 13px; color: #606266; margin-right: 8px">TTS 模型</span>
            <ModelSelect
              :model-value="cfg.sender?.tts_model || ''"
              :models="cfg.sender?.tts_enabled ? ttsModels : textModels"
              :required-caps="cfg.sender?.tts_enabled ? 'tts' : 'text_chat'"
              @change="(v: string) => handleSave('sender', 'model', v)" />
          </div>
          <div v-if="senderConflict" style="color: #f56c6c; font-size: 12px">
            冲突: {{ senderConflict }}
          </div>
        </div>
      </el-card>

    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { getModels, updateAgentConfig } from '@/api/config'
import client from '@/api/client'
import ModelSelect from './ModelSelect.vue'

const loading = ref(true)
const cfg = ref<any>({})
const allModels = ref<any[]>([])

const textAgents = [
  { key: 'scheduler', label: 'Scheduler' },
  { key: 'task', label: 'TaskAgent' },
  { key: 'memory', label: 'MemoryAgent' },
]

// 按能力分类的模型列表
const textModels = computed(() => allModels.value.filter((m: any) => m.enabled && m.capabilities.includes('text_chat')).map((m: any) => m.id))
const visionModels = computed(() => allModels.value.filter((m: any) => m.enabled && m.capabilities.includes('vision')).map((m: any) => m.id))
const audioModels = computed(() => allModels.value.filter((m: any) => m.enabled && m.capabilities.includes('audio_understanding')).map((m: any) => m.id))
const ttsModels = computed(() => allModels.value.filter((m: any) => m.enabled && m.capabilities.includes('tts')).map((m: any) => m.id))

function getTextModel(key: string): string {
  const map: Record<string, string> = { scheduler: 'scheduler', task: 'task', memory: 'memory' }
  return cfg.value[map[key]]?.model || ''
}
function getTextFallback(key: string): string {
  const map: Record<string, string> = { scheduler: 'scheduler', task: 'task', memory: 'memory' }
  return cfg.value[map[key]]?.fallback || ''
}

// 冲突检测
const receiverConflict = computed(() => {
  const c = cfg.value.receiver
  if (!c) return ''
  const msgs: string[] = []
  if (c.vision_enabled) {
    const m = allModels.value.find((x: any) => x.id === (c.vision_model || c.text_model))
    if (m && !m.capabilities.includes('vision')) msgs.push('视觉模型缺少 vision 能力')
  }
  if (c.audio_enabled) {
    const m = allModels.value.find((x: any) => x.id === (c.audio_model || c.text_model))
    if (m && !m.capabilities.includes('audio_understanding')) msgs.push('语音模型缺少 audio_understanding 能力')
  }
  return msgs.join('; ')
})

const senderConflict = computed(() => {
  const c = cfg.value.sender
  if (!c || !c.tts_enabled) return ''
  const m = allModels.value.find((x: any) => x.id === c.tts_model)
  if (m && !m.capabilities.includes('tts')) return 'TTS 模型缺少 tts 能力'
  return ''
})

onMounted(async () => {
  try {
    const [configRes, modelsRes] = await Promise.all([
      client.get('/config'),
      getModels(),
    ])
    cfg.value = configRes.data
    allModels.value = modelsRes.models
  } catch { }
  loading.value = false
})

async function handleSave(agentKey: string, field: string, value: any) {
  const body: Record<string, any> = {}
  if (field === 'model') body.model = value
  else if (field === 'fallback') body.fallback = value
  else if (field === 'vision_model') body.vision_model = value
  else if (field === 'audio_model') body.audio_model = value
  else body[field] = value

  try {
    await updateAgentConfig(agentKey, body)
    // 更新本地
    const c = cfg.value
    if (agentKey === 'receiver') {
      if (field === 'model') c.receiver.text_model = value
      if (field === 'vision_model') c.receiver.vision_model = value
      if (field === 'audio_model') c.receiver.audio_model = value
      if (field === 'vision_enabled') c.receiver.vision_enabled = value
      if (field === 'audio_enabled') c.receiver.audio_enabled = value
    } else if (agentKey === 'sender') {
      if (field === 'model') c.sender.tts_model = value
      if (field === 'tts_enabled') c.sender.tts_enabled = value
    } else {
      if (field === 'model') c[agentKey].model = value
      if (field === 'fallback') c[agentKey].fallback = value
    }
  } catch (e: any) {
    alert(e?.response?.data?.error || '保存失败')
  }
}
</script>
