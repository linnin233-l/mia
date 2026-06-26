import client from './client'

export async function getModels(): Promise<{ models: any[] }> {
  const { data } = await client.get('/models')
  return data
}

export async function toggleModel(modelId: string, enabled: boolean): Promise<void> {
  await client.put(`/models/${modelId}`, { enabled })
}

export async function updateAgentConfig(agentName: string, config: Record<string, any>): Promise<void> {
  await client.put(`/agents/${agentName}`, config)
}

export async function getAgentCapabilities(): Promise<Record<string, any>> {
  const { data } = await client.get('/agents/capabilities')
  return data
}
