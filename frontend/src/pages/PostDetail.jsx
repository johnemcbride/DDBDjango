import { useEffect, useState } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { getPost, getAuthor, addComment, deletePost } from '../api.js'

export default function PostDetail() {
  const { pk } = useParams()
  const navigate = useNavigate()
  const [post, setPost] = useState(null)
  const [author, setAuthor] = useState(null)
  const [comments, setComments] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [commentForm, setCommentForm] = useState({ author_name: '', body: '' })
  const [submitting, setSubmitting] = useState(false)
  const [commentError, setCommentError] = useState(null)

  useEffect(() => {
    getPost(pk)
      .then((data) => {
        setPost(data.post ?? data)
        setComments(data.comments ?? [])
        if (data.post?.author_id || data.author_id) {
          return getAuthor(data.post?.author_id ?? data.author_id)
        }
      })
      .then((a) => a && setAuthor(a))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [pk])

  const submitComment = async (e) => {
    e.preventDefault()
    setSubmitting(true)
    setCommentError(null)
    try {
      const c = await addComment(pk, commentForm)
      setComments((prev) => [...prev, c])
      setCommentForm({ author_name: '', body: '' })
    } catch (e) {
      setCommentError(e.message)
    } finally {
      setSubmitting(false)
    }
  }

  const handleDelete = async () => {
    if (!window.confirm('Delete this post?')) return
    await deletePost(pk)
    navigate('/')
  }

  if (loading) return <div className="loading">Loading…</div>
  if (error) return <div className="error-msg">{error}</div>
  if (!post) return <div className="empty">Post not found.</div>

  const date = post.created_at ? new Date(post.created_at).toLocaleDateString() : ''

  return (
    <article>
      <h1 className="page-title" style={{ marginBottom: '.5rem' }}>{post.title}</h1>

      <div className="post-meta">
        {author && <Link to={`/author/${post.author_id}`}>by {author.username}</Link>}
        {date && <span>{date}</span>}
        <span>👁 {post.view_count ?? 0} views</span>
        {!post.published && <span style={{ color: '#f59e0b', fontWeight: 600 }}>Draft</span>}
      </div>

      {Array.isArray(post.tags) && post.tags.length > 0 && (
        <div style={{ marginBottom: '1.5rem', display: 'flex', flexWrap: 'wrap', gap: '.4rem' }}>
          {post.tags.map((t, i) => <span key={i} className="chip chip-primary">{t}</span>)}
        </div>
      )}

      <div className="card" style={{ marginBottom: '2rem' }}>
        <div className="post-body">{post.body || <em style={{ color: 'var(--muted)' }}>No content.</em>}</div>
      </div>

      <div style={{ display: 'flex', gap: '.5rem', marginBottom: '2rem' }}>
        <Link to={`/write?pk=${pk}`} className="btn btn-ghost btn-sm">Edit</Link>
        <button onClick={handleDelete} className="btn btn-danger btn-sm">Delete</button>
        <Link to="/" className="btn btn-ghost btn-sm">← Back</Link>
      </div>

      <hr className="divider" />

      <section>
        <h2 className="section-title">Comments ({comments.length})</h2>
        {comments.length === 0 && <p className="empty" style={{ padding: '1rem 0' }}>No comments yet.</p>}
        {comments.map((c) => (
          <div key={c.pk} className="comment">
            <span className="author">{c.author_name || 'Anonymous'}</span>
            <span className="time">{c.created_at ? new Date(c.created_at).toLocaleDateString() : ''}</span>
            <p className="text">{c.body}</p>
          </div>
        ))}

        <form onSubmit={submitComment} style={{ marginTop: '1.5rem' }}>
          <h3 style={{ marginBottom: '1rem', fontSize: '1rem', fontWeight: 600 }}>Leave a comment</h3>
          <div className="form-field">
            <label>Name</label>
            <input
              value={commentForm.author_name}
              onChange={(e) => setCommentForm((p) => ({ ...p, author_name: e.target.value }))}
              placeholder="Your name"
            />
          </div>
          <div className="form-field">
            <label>Comment</label>
            <textarea
              value={commentForm.body}
              onChange={(e) => setCommentForm((p) => ({ ...p, body: e.target.value }))}
              placeholder="Write your comment…"
              required
            />
          </div>
          {commentError && <div className="error-msg">{commentError}</div>}
          <button type="submit" disabled={submitting} className="btn btn-primary">
            {submitting ? 'Posting…' : 'Post Comment'}
          </button>
        </form>
      </section>
    </article>
  )
}
