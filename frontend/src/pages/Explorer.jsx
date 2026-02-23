import { useEffect, useState, useCallback } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { getPosts, searchPosts, getTags, getCategories } from '../api.js'
import PostCard from '../components/PostCard.jsx'

export default function Explorer() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [posts, setPosts] = useState([])
  const [tags, setTags] = useState([])
  const [categories, setCategories] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [q, setQ] = useState(searchParams.get('q') || '')

  const load = useCallback(async (query) => {
    setLoading(true)
    setError(null)
    try {
      const [postsData, tagsData, catsData] = await Promise.all([
        query ? searchPosts(query) : getPosts(),
        getTags(),
        getCategories(),
      ])
      setPosts(postsData.posts ?? postsData ?? [])
      setTags(tagsData.tags ?? tagsData ?? [])
      setCategories(catsData.categories ?? catsData ?? [])
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const query = searchParams.get('q') || ''
    setQ(query)
    load(query)
  }, [searchParams, load])

  const handleSearch = (e) => {
    e.preventDefault()
    setSearchParams(q ? { q } : {})
  }

  return (
    <div>
      <h1 className="page-title">Explorer</h1>

      {/* Search */}
      <form onSubmit={handleSearch} style={{ display: 'flex', gap: '.5rem', marginBottom: '1.5rem' }}>
        <input
          className="form-field"
          style={{ flex: 1, margin: 0 }}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search posts…"
        />
        <button type="submit" className="btn btn-primary">Search</button>
        {searchParams.get('q') && (
          <button type="button" className="btn btn-ghost" onClick={() => setSearchParams({})}>
            Clear
          </button>
        )}
      </form>

      {searchParams.get('q') && (
        <p style={{ color: 'var(--muted)', marginBottom: '1rem', fontSize: '.9rem' }}>
          Results for <strong>"{searchParams.get('q')}"</strong>
        </p>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 260px', gap: '2rem', alignItems: 'start' }}>
        <section>
          {loading
            ? <div className="loading">Loading…</div>
            : error
            ? <div className="error-msg">{error}</div>
            : posts.length === 0
            ? <div className="empty">No posts found.</div>
            : posts.map((p) => <PostCard key={p.pk} post={p} />)
          }
        </section>

        <aside style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          {tags.length > 0 && (
            <div className="card">
              <div className="section-title">Tags</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '.4rem' }}>
                {tags.map((t) => (
                  <Link key={t.pk} to={`/tag/${t.pk}`} className="chip">{t.name}</Link>
                ))}
              </div>
            </div>
          )}
          {categories.length > 0 && (
            <div className="card">
              <div className="section-title">Categories</div>
              <ul style={{ listStyle: 'none' }}>
                {categories.map((c) => (
                  <li key={c.pk} style={{ marginBottom: '.4rem' }}>
                    <Link to={`/category/${c.pk}`}>{c.name}</Link>
                    {c.description && <p style={{ fontSize: '.78rem', color: 'var(--muted)' }}>{c.description}</p>}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </aside>
      </div>
    </div>
  )
}
