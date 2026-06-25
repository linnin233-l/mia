<template>
  <div>
    <h3>模型注册表</h3>
    <div v-if="loading" style="color: #909399; padding: 20px">加载中...</div>
    <el-table v-else :data="models" stripe>
      <el-table-column prop="id" label="模型 ID" width="180" />
      <el-table-column prop="provider" label="平台" width="100" />
      <el-table-column prop="desc" label="描述" min-width="260" />
      <el-table-column label="能力" width="260">
        <template #default="{ row }">
          <el-tag v-for="cap in row.capabilities" :key="cap" size="small" style="margin-right: 3px">
            {{ cap }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="启用" width="90" align="center">
        <template #default="{ row }">
          <el-switch
            :model-value="row.enabled"
            :disabled="!row.has_key"
            :loading="toggling[row.id]"
            @change="(val: boolean) => handleToggle(row.id, val)"
          />
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { getModels, toggleModel } from '@/api/config'

const models = ref<any[]>([])
const loading = ref(true)
const toggling = ref<Record<string, boolean>>({})

onMounted(async () => {
  try {
    const data = await getModels()
    models.value = data.models
  } catch {}
  loading.value = false
})

async function handleToggle(modelId: string, enabled: boolean) {
  toggling.value[modelId] = true
  try {
    await toggleModel(modelId, enabled)
    const m = models.value.find((x: any) => x.id === modelId)
    if (m) m.enabled = enabled
  } catch {}
  toggling.value[modelId] = false
}
</script>
