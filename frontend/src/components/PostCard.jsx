import { Link } from 'react-router-dom'

export default function PostCard({ post }) {
  const preview = post.body ? post.body.slice(0, 160) + (post.body.length > 160 ? '…' : '') : ''
  const date = post.created_at ? new Date(post.created_at).toLocaleDateString() : ''

  return (
    <div className="card post-card">
      <h2><Link to={`/post/${post.pk}`}>{post.title}</Link></h2>
      <div className="meta">
        {post.author_id && (
          <Link to={`/author/${post.author_id}`}>Author</Link>
        )}
        {date && <span>{date}</span>}
        <span>👁 {post.view_count ?? 0}</span>
        {!post.published && <span style={{ color: '#f59e0b' }}>Draft</span>}
      </div>
      {preview && <p className="body-preview">{preview}</p>}
      {Array.isArray(post.tags) && post.tags.length > 0 && (
        <div style={{ marginTop: '.5rem' }}>
          {post.tags.map((t, i) => (
            <span key={i} className="tag-pill">{t}</span>
          ))}
        </div>
      )}
    </div>
  )
}
