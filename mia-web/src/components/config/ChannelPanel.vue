<template>
  <div>
    <h3>Channel Configuration</h3>
    <div v-if="loading" style="color: #909399; padding: 20px">Loading...</div>
    <div v-else style="display: flex; flex-direction: column; gap: 16px; max-width: 560px">
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
            <el-tag :type="ch.enabled ? 'success' : 'info'" size="small" style="margin-left: 6px">
              {{ ch.enabled ? 'Enabled' : 'Disabled' }}
            </el-tag>
          </div>
          <div v-if="ch.detail && ch.hasToken" style="color: #606266; line-height: 1.8">
            <div>Token: <code style="background: #f5f5f5; padding: 1px 6px; border-radius: 3px">{{ ch.detail.token_masked || '-' }}</code></div>
            <div>File: <span style="font-size: 12px; color: #909399">{{ ch.detail.token_file || '-' }}</span></div>
            <div v-if="ch.detail.file_size">
              Size: {{ (ch.detail.file_size / 1024).toFixed(1) }} KB
              &nbsp;|&nbsp; Updated: {{ ch.detail.file_mtime || '-' }}
            </div>
          </div>
          <div v-else-if="!ch.hasToken" style="color: #909399; font-size: 12px">
            No token file found at {{ ch.detail?.token_file || '~/.mia/' + ch.key + '_bot_token' }}
          </div>
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useChannelStore } from '@/stores/channels'
import { getInterfaceDetail } from '@/api/channels'

const channelStore = useChannelStore()
const loading = ref(true)
const toggling = ref<Record<string, boolean>>({})
const details = ref<Record<string, any>>({})

onMounted(async () => {
  await channelStore.fetchStatus()
  // 加载每个接口的详细信息
  for (const name of ['wechat', 'telegram']) {
    try {
      details.value[name] = await getInterfaceDetail(name)
    } catch {
      details.value[name] = null
    }
  }
  loading.value = false
})

const channelList = computed(() => [
  {
    key: 'wechat',
    label: 'WeChat (iLink Bot)',
    enabled: channelStore.channels.wechat?.enabled ?? false,
    hasToken: channelStore.channels.wechat?.has_token ?? false,
    toggling: toggling.value['wechat'] ?? false,
    detail: details.value['wechat'],
  },
  {
    key: 'telegram',
    label: 'Telegram (Bot API)',
    enabled: channelStore.channels.telegram?.enabled ?? false,
    hasToken: channelStore.channels.telegram?.has_token ?? false,
    toggling: toggling.value['telegram'] ?? false,
    detail: details.value['telegram'],
  },
])

async function handleToggle(name: string, enabled: boolean) {
  toggling.value[name] = true
  try {
    await channelStore.toggle(name, enabled)
    // 刷新详情
    details.value[name] = await getInterfaceDetail(name)
  } catch {
  } finally {
    toggling.value[name] = false
  }
}
</script>
