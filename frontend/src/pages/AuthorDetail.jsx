import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { getAuthor, getAuthorPosts, getAuthorProfile } from '../api.js'
import PostCard from '../components/PostCard.jsx'

export default function AuthorDetail() {
  const { pk } = useParams()
  const [author, setAuthor] = useState(null)
  const [profile, setProfile] = useState(null)
  const [posts, setPosts] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    Promise.all([
      getAuthor(pk),
      getAuthorPosts(pk),
      getAuthorProfile(pk).catch(() => null),
    ])
      .then(([a, postsData, prof]) => {
        setAuthor(a)
        setPosts(postsData.posts ?? postsData ?? [])
        setProfile(prof)
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [pk])

  if (loading) return <div className="loading">Loading…</div>
  if (error) return <div className="error-msg">{error}</div>
  if (!author) return <div className="empty">Author not found.</div>

  return (
    <div>
      <div className="card" style={{ marginBottom: '2rem' }}>
        <h1 className="page-title" style={{ marginBottom: '.5rem' }}>
          {author.username}
          {profile?.location && <small> · {profile.location}</small>}
        </h1>
        {author.bio && <p style={{ color: 'var(--muted)', marginBottom: '1rem' }}>{author.bio}</p>}
        <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', fontSize: '.85rem' }}>
          {author.email && <span>📧 {author.email}</span>}
          {profile?.website && <a href={profile.website} target="_blank" rel="noreferrer">🔗 Website</a>}
          {profile?.twitter && <a href={`https://twitter.com/${profile.twitter}`} target="_blank" rel="noreferrer">🐦 @{profile.twitter}</a>}
          {profile?.follower_count > 0 && <span>👥 {profile.follower_count} followers</span>}
        </div>
      </div>

      <h2 className="section-title">Posts by {author.username} ({posts.length})</h2>
      {posts.length === 0
        ? <div className="empty">No posts yet.</div>
        : posts.map((p) => <PostCard key={p.pk} post={p} />)
      }
      <div style={{ marginTop: '1.5rem' }}>
        <Link to="/" className="btn btn-ghost btn-sm">← Back</Link>
      </div>
    </div>
  )
}
