<template>
  <el-select
    :model-value="modelValue"
    size="small"
    style="width: 190px"
    :clearable="clearable"
    @change="(v: any) => $emit('change', v)"
  >
    <el-option v-for="m in options" :key="m.id" :label="m.label" :value="m.id"
      :disabled="m.disabled" />
  </el-select>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  modelValue: string
  models: string[]
  requiredCaps: string
  clearable?: boolean
}>()

defineEmits<{ change: [value: string] }>()

const options = computed(() => {
  return props.models.map(id => ({
    id,
    label: id,
    disabled: false,
  }))
})
</script>
