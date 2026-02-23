import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { getTags, getPostsByTag } from '../api.js'
import PostCard from '../components/PostCard.jsx'

export default function TagDetail() {
  const { pk } = useParams()
  const [tag, setTag] = useState(null)
  const [posts, setPosts] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    Promise.all([
      getTags().then((d) => (d.tags ?? d ?? []).find((t) => t.pk === pk)),
      getPostsByTag(pk).catch(() => ({ posts: [] })),
    ])
      .then(([t, postsData]) => {
        setTag(t ?? { pk, name: 'Tag' })
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
        Tag: <span className="chip chip-primary" style={{ fontSize: '1.2rem', padding: '.2rem .8rem' }}>
          {tag?.name ?? pk}
        </span>
        <small>{posts.length} posts</small>
      </h1>
      {tag?.colour && tag.colour !== '#cccccc' && (
        <span style={{ display: 'inline-block', width: 16, height: 16, borderRadius: '50%', background: tag.colour, marginBottom: '1rem' }} />
      )}
      {posts.length === 0
        ? <div className="empty">No posts for this tag.</div>
        : posts.map((p) => <PostCard key={p.pk} post={p} />)
      }
      <div style={{ marginTop: '1.5rem' }}>
        <Link to="/explorer" className="btn btn-ghost btn-sm">← Explorer</Link>
      </div>
    </div>
  )
}
