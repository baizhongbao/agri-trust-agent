// 后端接口封装。
// 开发期由 Vite 代理转发到 127.0.0.1:8000，因此这里只写相对路径。
// 部署时若前后端不同源，设置 VITE_API_BASE 即可。

const BASE = import.meta.env.VITE_API_BASE || ''

async function request(path, options = {}) {
  const response = await fetch(`${BASE}${path}`, options)

  if (!response.ok) {
    let detail = `请求失败（HTTP ${response.status}）`
    try {
      const payload = await response.json()
      if (payload && payload.detail) detail = payload.detail
    } catch {
      // 响应不是 JSON，保留默认提示
    }
    throw new Error(detail)
  }

  return response.json()
}

function postJson(path, body) {
  return request(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export const getHealth = () => request('/health')

export const parseContract = (file) => {
  const form = new FormData()
  form.append('file', file)
  return request('/api/v1/contracts/parse', { method: 'POST', body: form })
}

export const listContracts = () => request('/api/v1/contracts')

export const getContract = (docId) => request(`/api/v1/contracts/${docId}`)

export const checkStandards = (docId, topK = 3) =>
  postJson('/api/v1/standards/check', { doc_id: docId, top_k: topK })

export const searchStandards = (query, topK = 5) =>
  postJson('/api/v1/standards/search', { query, top_k: topK })

export const getStandardLibrary = () => request('/api/v1/standards')

export const getStandardStats = () => request('/api/v1/standards/stats')

export const verifyContract = (docId) =>
  postJson('/api/v1/enterprise/verify', { doc_id: docId })

export const lookupEnterprise = (searchKey) =>
  postJson('/api/v1/enterprise/lookup', { search_key: searchKey })

export const simulateContract = (docId, scenarios = null, params = {}) =>
  postJson(`/api/v1/simulate/${docId}`, { doc_id: docId, scenarios, params })

export const getSimulationRules = () => request('/api/v1/simulate/rules')

export const evaluateVerdict = (docId) =>
  postJson('/api/v1/verdict/evaluate', { doc_id: docId })

export const verdictReportUrl = (docId, format = 'pdf') =>
  `${BASE}/api/v1/verdict/${encodeURIComponent(docId)}/report?format=${format}`
