<template>
  <div>
    <h3>Channel Configuration</h3>
    <div v-if="loading" style="color: #909399; padding: 20px">Loading channel status...</div>
    <div v-else style="display: flex; flex-direction: column; gap: 16px; max-width: 500px">
      <el-card v-for="ch in channelList" :key="ch.key">
        <template #header>
          <div style="display: flex; justify-content: space-between; align-items: center">
            <span style="font-weight: 500">{{ ch.label }}</span>
            <el-switch
              :model-value="ch.enabled"
              :loading="ch.toggling"
              @change="(val: boolean) => handleToggle(ch.key, val)"
            />
          </div>
        </template>
        <div style="display: flex; flex-direction: column; gap: 8px; font-size: 13px">
          <div>
            <el-tag :type="ch.hasToken ? 'success' : 'warning'" size="small">
              {{ ch.hasToken ? 'Token configured' : 'No token' }}
            </el-tag>
          </div>
          <div v-if="ch.tokenStatus" style="color: #909399">
            <div v-if="ch.tokenStatus.error">
              <el-tag type="danger" size="small">Error: {{ ch.tokenStatus.error }}</el-tag>
            </div>
          </div>
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useChannelStore } from '@/stores/channels'

const channelStore = useChannelStore()
const loading = ref(true)
const toggling = ref<Record<string, boolean>>({})

onMounted(async () => {
  await channelStore.fetchStatus()
  loading.value = false
})

const channelList = computed(() => [
  {
    key: 'wechat',
    label: 'WeChat (iLink Bot)',
    enabled: channelStore.channels.wechat?.enabled ?? false,
    hasToken: channelStore.channels.wechat?.has_token ?? false,
    toggling: toggling.value['wechat'] ?? false,
  },
  {
    key: 'telegram',
    label: 'Telegram (Bot API)',
    enabled: channelStore.channels.telegram?.enabled ?? false,
    hasToken: channelStore.channels.telegram?.has_token ?? false,
    toggling: toggling.value['telegram'] ?? false,
  },
])

async function handleToggle(name: string, enabled: boolean) {
  toggling.value[name] = true
  try {
    await channelStore.toggle(name, enabled)
  } catch {
    // silently fail, store might have retry
  } finally {
    toggling.value[name] = false
  }
}
</script>
