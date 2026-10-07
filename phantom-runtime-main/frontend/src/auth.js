import axios from 'axios'

// The backend requires an API key on every REST call and on both WebSockets. The key is kept in
// localStorage (per browser) and attached to requests; set it from the field in the app header.
const STORAGE_KEY = 'phantom_api_key'
const listeners = new Set()

export function getApiKey() {
  try {
    return window.localStorage.getItem(STORAGE_KEY) || ''
  } catch {
    return ''
  }
}

export function setApiKey(key) {
  const value = (key || '').trim()
  try {
    if (value) window.localStorage.setItem(STORAGE_KEY, value)
    else window.localStorage.removeItem(STORAGE_KEY)
  } catch {
    // storage unavailable (private window): the key then only lives until reload via the listeners
  }
  listeners.forEach((fn) => fn(value))
}

export function onApiKeyChange(fn) {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

export function installAuth(instance) {
  instance.interceptors.request.use((config) => {
    const key = getApiKey()
    if (key) config.headers['X-API-Key'] = key
    return config
  })
  return instance
}

// the default axios instance (used directly by several components)
installAuth(axios)
