<template>
  <div>
    <h3>渠道配置</h3>
    <div v-if="loading" style="color: #909399; padding: 20px">加载中...</div>
    <div v-else style="display: flex; flex-direction: column; gap: 16px; max-width: 660px">
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
        <div style="display: flex; flex-direction: column; gap: 8px; font-size: 13px; line-height: 1.8">
          <!-- Status row -->
          <div>
            <el-tag :type="ch.hasToken ? 'success' : 'warning'" size="small">{{ ch.hasToken ? '已绑定' : '未绑定' }}</el-tag>
            <el-tag :type="ch.enabled ? 'success' : 'info'" size="small" style="margin-left: 6px">{{ ch.enabled ? '启用' : '已关闭' }}</el-tag>
            <span style="margin-left: 8px; color: #909399; font-size: 12px">{{ ch.detail?.login_method || '-' }}</span>
          </div>

          <!-- Token info -->
          <div v-if="ch.hasToken && ch.detail?.token_masked" style="background: #fafafa; padding: 8px 12px; border-radius: 4px">
            <div><span style="color: #606266">Token: </span><code>{{ ch.detail.token_masked }}</code></div>
            <div style="color: #909399; font-size: 12px">文件: {{ ch.detail.token_file }}</div>
            <div style="color: #909399; font-size: 12px" v-if="ch.detail.file_size">
              大小: {{ (ch.detail.file_size / 1024).toFixed(1) }} KB
              | 更新: {{ ch.detail.file_mtime || '-' }}
            </div>
            <div style="color: #909399; font-size: 12px">API: {{ ch.detail.base_url }}</div>
          </div>

          <!-- We聊天 context tokens (unique to We聊天) -->
          <div v-if="ch.key === 'wechat' && ch.detail?.ctx_file" style="background: #f0f9eb; padding: 8px 12px; border-radius: 4px">
            <div style="color: #67c23a; font-weight: 500; font-size: 12px">Context Tokens (用户路由缓存)</div>
            <div style="color: #909399; font-size: 12px">
              {{ ch.detail.ctx_user_count ?? 0 }} 活跃用户
              | {{ ((ch.detail.ctx_file_size ?? 0) / 1024).toFixed(1) }} KB
              | {{ ch.detail.ctx_file_mtime || '-' }}
            </div>
            <div style="color: #c0c4cc; font-size: 11px; word-break: break-all">{{ ch.detail.ctx_file }}</div>
          </div>

          <!-- 无 Token state -->
          <div v-if="!ch.hasToken" style="background: #fef0f0; padding: 8px 12px; border-radius: 4px; color: #f56c6c; font-size: 12px">
            <div v-if="ch.key === 'wechat'">未登录。请用 CLI <code>/interface</code> 扫码登录，或在下方粘贴 Token。</div>
            <div v-else>未配置 Token。请在 Telegram 找 @BotFather 获取。</div>
          </div>

          <!-- Token editing -->
          <div v-if="editState[ch.key].editing" style="margin-top: 4px">
            <el-input
              v-model="editState[ch.key].editToken"
              type="password"
              show-password
              placeholder="在此粘贴 Token"
              size="small"
              style="margin-bottom: 6px"
            />
            <div style="display: flex; gap: 6px">
              <el-button size="small" type="primary" :loading="editState[ch.key].saving" @click="handleSaveToken(ch.key)">保存</el-button>
              <el-button size="small" @click="cancelEdit(ch.key)">取消</el-button>
            </div>
          </div>
          <div v-else>
            <el-button size="small" @click="startEdit(ch.key)">
              {{ ch.hasToken ? '更新 Token' : '设置 Token' }}
            </el-button>
          </div>
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, computed, onMounted } from 'vue'
import { useChannelStore } from '@/stores/channels'
import { getInterfaceDetail, updateInterfaceToken } from '@/api/channels'
import { ElMessage } from 'element-plus'

const channelStore = useChannelStore()
const loading = ref(true)
const toggling = ref<Record<string, boolean>>({})
const details = ref<Record<string, any>>({})

const editState = reactive<Record<string, { editing: boolean; editToken: string; saving: boolean }>>({
  wechat: { editing: false, editToken: '', saving: false },
  telegram: { editing: false, editToken: '', saving: false },
})

onMounted(async () => {
  await channelStore.fetchStatus()
  for (const name of ['wechat', 'telegram']) {
    try { details.value[name] = await getInterfaceDetail(name) } catch { details.value[name] = null }
  }
  loading.value = false
})

const channelList = computed(() => [
  { key: 'wechat' as const, label: '微信 (iLink Bot)', enabled: channelStore.channels.wechat?.enabled ?? false, hasToken: channelStore.channels.wechat?.has_token ?? false, toggling: toggling.value['wechat'] ?? false, detail: details.value['wechat'] },
  { key: 'telegram' as const, label: '纸飞机 (Bot API)', enabled: channelStore.channels.telegram?.enabled ?? false, hasToken: channelStore.channels.telegram?.has_token ?? false, toggling: toggling.value['telegram'] ?? false, detail: details.value['telegram'] },
])

function startEdit(name: string) { editState[name].editing = true; editState[name].editToken = '' }
function cancelEdit(name: string) { editState[name].editing = false; editState[name].editToken = '' }

async function handleToggle(name: string, enabled: boolean) {
  toggling.value[name] = true
  try { await channelStore.toggle(name, enabled); details.value[name] = await getInterfaceDetail(name) } catch {} finally { toggling.value[name] = false }
}

async function handleSaveToken(name: string) {
  const st = editState[name]
  if (!st.editToken.trim()) return
  st.saving = true
  try {
    await updateInterfaceToken(name, st.editToken.trim())
    details.value[name] = await getInterfaceDetail(name)
    st.editing = false; st.editToken = ''
    ElMessage.success(`${name} Token 已更新`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '失败')
  } finally { st.saving = false }
}
</script>
