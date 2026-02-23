import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

export default function Header() {
  const [q, setQ] = useState('')
  const navigate = useNavigate()

  const handleSearch = (e) => {
    e.preventDefault()
    if (q.trim()) navigate(`/explorer?q=${encodeURIComponent(q.trim())}`)
  }

  return (
    <header className="site-nav">
      <div className="inner">
        <Link to="/" className="brand">
          DDB<span>Django</span>
        </Link>
        <form className="search-bar" onSubmit={handleSearch}>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search posts…"
            aria-label="Search"
          />
          <button type="submit" className="btn btn-primary btn-sm">Go</button>
        </form>
        <nav>
          <Link to="/">Home</Link>
          <Link to="/explorer">Explorer</Link>
          <Link to="/write">Write</Link>
        </nav>
      </div>
    </header>
  )
}
