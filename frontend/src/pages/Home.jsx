import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getPosts, getTags, getCategories } from '../api.js'
import PostCard from '../components/PostCard.jsx'

export default function Home() {
  const [posts, setPosts] = useState([])
  const [tags, setTags] = useState([])
  const [categories, setCategories] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    Promise.all([getPosts({ published: true }), getTags(), getCategories()])
      .then(([postsData, tagsData, catsData]) => {
        setPosts(postsData.posts ?? postsData ?? [])
        setTags(tagsData.tags ?? tagsData ?? [])
        setCategories(catsData.categories ?? catsData ?? [])
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="loading">Loading…</div>
  if (error) return <div className="error-msg">{error}</div>

  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 280px', gap: '2rem', alignItems: 'start' }}>
        {/* Main feed */}
        <section>
          <h1 className="page-title">Latest Posts</h1>
          {posts.length === 0
            ? <div className="empty">No posts yet. <Link to="/write">Write one!</Link></div>
            : posts.map((p) => <PostCard key={p.pk} post={p} />)
          }
        </section>

        {/* Sidebar */}
        <aside>
          {tags.length > 0 && (
            <div className="card" style={{ marginBottom: '1rem' }}>
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
              <ul style={{ listStyle: 'none', paddingLeft: 0 }}>
                {categories.map((c) => (
                  <li key={c.pk} style={{ marginBottom: '.4rem' }}>
                    <Link to={`/category/${c.pk}`}>{c.name}</Link>
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
