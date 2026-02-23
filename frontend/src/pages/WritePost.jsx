import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams, Link } from 'react-router-dom'
import { getPost, createPost, updatePost, getAuthors, createAuthor } from '../api.js'

export default function WritePost() {
  const [searchParams] = useSearchParams()
  const editPk = searchParams.get('pk')
  const navigate = useNavigate()

  const [form, setForm] = useState({
    title: '', slug: '', body: '', tags: '', published: false, author_id: '',
  })
  const [authors, setAuthors] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [newAuthor, setNewAuthor] = useState('')
  const [addingAuthor, setAddingAuthor] = useState(false)

  useEffect(() => {
    getAuthors()
      .then((d) => setAuthors(d.authors ?? d ?? []))
      .catch(() => {})

    if (editPk) {
      setLoading(true)
      getPost(editPk)
        .then((d) => {
          const p = d.post ?? d
          setForm({
            title: p.title ?? '',
            slug: p.slug ?? '',
            body: p.body ?? '',
            tags: Array.isArray(p.tags) ? p.tags.join(', ') : '',
            published: p.published ?? false,
            author_id: p.author_id ?? '',
          })
        })
        .catch((e) => setError(e.message))
        .finally(() => setLoading(false))
    }
  }, [editPk])

  const set = (field) => (e) =>
    setForm((p) => ({ ...p, [field]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }))

  const handleAddAuthor = async () => {
    if (!newAuthor.trim()) return
    setAddingAuthor(true)
    try {
      const a = await createAuthor({ username: newAuthor.trim() })
      setAuthors((prev) => [...prev, a])
      setForm((p) => ({ ...p, author_id: a.pk }))
      setNewAuthor('')
    } catch (e) {
      setError(e.message)
    } finally {
      setAddingAuthor(false)
    }
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    setError(null)
    const payload = {
      ...form,
      tags: form.tags.split(',').map((t) => t.trim()).filter(Boolean),
    }
    try {
      let post
      if (editPk) {
        post = await updatePost(editPk, payload)
      } else {
        post = await createPost(payload)
      }
      navigate(`/post/${post.pk ?? editPk}`)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ maxWidth: 640 }}>
      <h1 className="page-title">{editPk ? 'Edit Post' : 'Write a Post'}</h1>

      <form onSubmit={handleSubmit} className="card">
        <div className="form-field">
          <label>Author</label>
          <select value={form.author_id} onChange={set('author_id')} required>
            <option value="">— select author —</option>
            {authors.map((a) => (
              <option key={a.pk} value={a.pk}>{a.username}</option>
            ))}
          </select>
        </div>

        <div style={{ display: 'flex', gap: '.5rem', marginBottom: '1rem', alignItems: 'flex-end' }}>
          <div className="form-field" style={{ flex: 1, margin: 0 }}>
            <label>Or add new author</label>
            <input value={newAuthor} onChange={(e) => setNewAuthor(e.target.value)} placeholder="username" />
          </div>
          <button type="button" className="btn btn-ghost" onClick={handleAddAuthor} disabled={addingAuthor}>
            {addingAuthor ? '…' : 'Add'}
          </button>
        </div>

        <div className="form-field">
          <label>Title</label>
          <input value={form.title} onChange={set('title')} required placeholder="Post title" />
        </div>

        <div className="form-field">
          <label>Slug</label>
          <input
            value={form.slug}
            onChange={set('slug')}
            required
            placeholder="my-post-slug"
            onBlur={() => {
              if (!form.slug && form.title)
                setForm((p) => ({ ...p, slug: p.title.toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, '') }))
            }}
          />
        </div>

        <div className="form-field">
          <label>Body</label>
          <textarea value={form.body} onChange={set('body')} placeholder="Write your post…" style={{ minHeight: 240 }} />
        </div>

        <div className="form-field">
          <label>Tags <span style={{ color: 'var(--muted)', fontWeight: 400 }}>(comma-separated)</span></label>
          <input value={form.tags} onChange={set('tags')} placeholder="django, dynamodb, aws" />
        </div>

        <div className="form-field" style={{ display: 'flex', alignItems: 'center', gap: '.75rem' }}>
          <input
            id="published"
            type="checkbox"
            checked={form.published}
            onChange={set('published')}
            style={{ width: 'auto' }}
          />
          <label htmlFor="published" style={{ marginBottom: 0 }}>Publish immediately</label>
        </div>

        {error && <div className="error-msg">{error}</div>}

        <div className="form-actions">
          <button type="submit" disabled={loading} className="btn btn-primary">
            {loading ? 'Saving…' : editPk ? 'Save Changes' : 'Publish Post'}
          </button>
          <Link to="/" className="btn btn-ghost">Cancel</Link>
        </div>
      </form>
    </div>
  )
}
