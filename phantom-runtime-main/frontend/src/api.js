import axios from 'axios'

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || 'http://localhost:8001'

const api = axios.create({
  baseURL: BACKEND_URL,
  headers: {
    'Content-Type': 'application/json',
  },
})

export const eventsAPI = {
  createEvent: (data) => api.post('/api/events/', data),
  getEntityEvents: (entityId) => api.get(`/api/events/entity/${entityId}`),
  getAllEvents: (limit = 100) => api.get(`/api/events/`, { params: { limit } }),
}

export const stateAPI = {
  getEntityState: (entityId) => api.get(`/api/state/${entityId}`),
  getAllEntities: () => api.get('/api/state/'),
  runAgent: (data) => api.post('/api/state/agent/run', data),
}

export const healthAPI = {
  check: () => api.get('/api/health'),
}

export default api
