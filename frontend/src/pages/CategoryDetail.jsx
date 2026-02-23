import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { getCategories, getPostsByCategory } from '../api.js'
import PostCard from '../components/PostCard.jsx'

export default function CategoryDetail() {
  const { pk } = useParams()
  const [category, setCategory] = useState(null)
  const [posts, setPosts] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    Promise.all([
      getCategories().then((d) => (d.categories ?? d ?? []).find((c) => c.pk === pk)),
      getPostsByCategory(pk).catch(() => ({ posts: [] })),
    ])
      .then(([c, postsData]) => {
        setCategory(c ?? { pk, name: 'Category' })
        setPosts(postsData.posts ?? postsData ?? [])
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [pk])

  if (loading) return <div className="loading">Loading…</div>
  if (error) return <div className="error-msg">{error}</div>

  return (
    <div>
      <h1 className="page-title">
        {category?.name ?? pk}
        <small>{posts.length} posts</small>
      </h1>
      {category?.description && (
        <p style={{ color: 'var(--muted)', marginBottom: '1.5rem' }}>{category.description}</p>
      )}
      {category?.parent_id && (
        <p style={{ marginBottom: '1rem', fontSize: '.875rem' }}>
          Parent: <Link to={`/category/${category.parent_id}`}>View parent category</Link>
        </p>
      )}
      {posts.length === 0
        ? <div className="empty">No posts in this category.</div>
        : posts.map((p) => <PostCard key={p.pk} post={p} />)
      }
      <div style={{ marginTop: '1.5rem' }}>
        <Link to="/explorer" className="btn btn-ghost btn-sm">← Explorer</Link>
      </div>
    </div>
  )
}
