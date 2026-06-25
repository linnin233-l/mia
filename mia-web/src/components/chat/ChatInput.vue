<template>
  <div style="border-top: 1px solid #e4e7ed; padding: 12px 20px; display: flex; gap: 8px; align-items: flex-end">
    <el-input
      v-model="text"
      type="textarea"
      :rows="2"
      placeholder="输入消息... (Enter 发送, Shift+Enter 换行)"
      resize="none"
      :disabled="loading"
      @keydown.enter.exact.prevent="handle发送"
    />
    <el-button type="primary" :disabled="!text.trim() || loading" @click="handle发送" :loading="loading">
      发送
    </el-button>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{ loading: boolean }>()
const emit = defineEmits<{ send: [text: string] }>()

const text = ref('')

function handle发送() {
  const msg = text.value.trim()
  if (!msg) return
  emit('send', msg)
  text.value = ''
}
</script>
