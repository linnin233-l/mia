<template>
  <div style="padding: 20px">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px">
      <h2 style="margin: 0">会话</h2>
      <el-button type="primary" @click="show创建 = true">新建会话</el-button>
    </div>

    <el-table :data="sessionStore.sessions" v-loading="sessionStore.loading" stripe>
      <el-table-column prop="name" label="名称" min-width="150" />
      <el-table-column label="来源" width="100">
        <template #default="{ row }">
          <el-tag size="small">{{ sourceLabel(row.source) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="turn_count" label="轮次" width="80" />
      <el-table-column prop="created_at" label="创建时间" width="170">
        <template #default="{ row }">{{ row.created_at?.slice(0, 16) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="260">
        <template #default="{ row }">
          <el-button
            size="small"
            :type="row.session_id === sessionStore.currentId ? 'success' : 'default'"
            @click="handleActivate(row.session_id)"
          >
            {{ row.session_id === sessionStore.currentId ? '当前' : '切换' }}
          </el-button>
          <el-button size="small" @click="handle重命名(row)">重命名</el-button>
          <el-button size="small" type="danger" @click="handle删除(row.session_id)" :disabled="sessionStore.sessions.length <= 1">
            删除
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="show创建" title="新建会话" width="400px">
      <el-input v-model="new名称" placeholder="会话名称" @keyup.enter="handle创建" />
      <template #footer>
        <el-button @click="show创建 = false">取消</el-button>
        <el-button type="primary" @click="handle创建" :disabled="!new名称.trim()">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="show重命名" title="重命名 Session" width="400px">
      <el-input v-model="renameValue" placeholder="新名称" @keyup.enter="handle重命名确认" />
      <template #footer>
        <el-button @click="show重命名 = false">取消</el-button>
        <el-button type="primary" @click="handle重命名确认">确认</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useSessionStore } from '@/stores/sessions'
import type { SessionInfo } from '@/types'

const sessionStore = useSessionStore()

const show创建 = ref(false)
const show重命名 = ref(false)
const new名称 = ref('')
const renameTarget = ref<SessionInfo | null>(null)
const renameValue = ref('')

onMounted(() => sessionStore.fetch会话())

function sourceLabel(source: string) {
  return { cli: 'CLI', wechat: 'We聊天', telegram: 'TG', api: 'API' }[source] || source
}

async function handle创建() {
  if (!new名称.value.trim()) return
  await sessionStore.create(new名称.value.trim())
  new名称.value = ''
  show创建.value = false
}

function handle重命名(row: SessionInfo) {
  renameTarget.value = row
  renameValue.value = row.name
  show重命名.value = true
}

async function handle重命名确认() {
  if (!renameTarget.value || !renameValue.value.trim()) return
  await sessionStore.rename(renameTarget.value.session_id, renameValue.value.trim())
  show重命名.value = false
}

async function handleActivate(id: string) {
  await sessionStore.activate(id)
}

async function handle删除(id: string) {
  try {
    await sessionStore.remove(id)
  } catch {}
}
</script>
