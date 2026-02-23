/**
 * API client — base URL is baked in at build time via VITE_API_URL.
 * In local dev, Vite proxies /api → http://localhost:8000 so the variable
 * is not needed and falls back to the empty string.
 */
const BASE = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '')

async function request(path, options = {}) {
  const url = `${BASE}${path}`
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`${res.status} ${res.statusText}: ${text}`)
  }
  // 204 No Content
  if (res.status === 204) return null
  return res.json()
}

// ── Posts ────────────────────────────────────────────────────────────────────
export const getPosts = (params = {}) => {
  const qs = new URLSearchParams(params).toString()
  return request(`/api/posts/${qs ? '?' + qs : ''}`)
}
export const getPost = (pk) => request(`/api/posts/${pk}/`)
export const createPost = (data) =>
  request('/api/posts/', { method: 'POST', body: JSON.stringify(data) })
export const updatePost = (pk, data) =>
  request(`/api/posts/${pk}/`, { method: 'PUT', body: JSON.stringify(data) })
export const deletePost = (pk) => request(`/api/posts/${pk}/`, { method: 'DELETE' })
export const searchPosts = (q) => request(`/api/posts/search/?q=${encodeURIComponent(q)}`)

// ── Comments ─────────────────────────────────────────────────────────────────
export const addComment = (postPk, data) =>
  request(`/api/posts/${postPk}/comments/`, { method: 'POST', body: JSON.stringify(data) })
export const deleteComment = (pk) => request(`/api/comments/${pk}/`, { method: 'DELETE' })

// ── Authors ──────────────────────────────────────────────────────────────────
export const getAuthors = () => request('/api/authors/')
export const getAuthor = (pk) => request(`/api/authors/${pk}/`)
export const getAuthorPosts = (pk, params = {}) => {
  const qs = new URLSearchParams(params).toString()
  return request(`/api/authors/${pk}/posts/${qs ? '?' + qs : ''}`)
}
export const getAuthorProfile = (pk) => request(`/api/authors/${pk}/profile/`)
export const createAuthor = (data) =>
  request('/api/authors/', { method: 'POST', body: JSON.stringify(data) })

// ── Tags ─────────────────────────────────────────────────────────────────────
export const getTags = () => request('/api/tags/')
export const createTag = (data) =>
  request('/api/tags/', { method: 'POST', body: JSON.stringify(data) })
export const getPostsByTag = (tagPk) => request(`/api/posts/?tag_pk=${tagPk}`)

// ── Categories ───────────────────────────────────────────────────────────────
export const getCategories = () => request('/api/categories/')
export const createCategory = (data) =>
  request('/api/categories/', { method: 'POST', body: JSON.stringify(data) })
export const getPostsByCategory = (catPk) => request(`/api/posts/?category_pk=${catPk}`)
