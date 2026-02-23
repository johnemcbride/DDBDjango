import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Header from './components/Header.jsx'
import Home from './pages/Home.jsx'
import Explorer from './pages/Explorer.jsx'
import PostDetail from './pages/PostDetail.jsx'
import WritePost from './pages/WritePost.jsx'
import AuthorDetail from './pages/AuthorDetail.jsx'
import TagDetail from './pages/TagDetail.jsx'
import CategoryDetail from './pages/CategoryDetail.jsx'

export default function App() {
  return (
    <BrowserRouter>
      <Header />
      <main className="container">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/explorer" element={<Explorer />} />
          <Route path="/write" element={<WritePost />} />
          <Route path="/post/:pk" element={<PostDetail />} />
          <Route path="/author/:pk" element={<AuthorDetail />} />
          <Route path="/tag/:pk" element={<TagDetail />} />
          <Route path="/category/:pk" element={<CategoryDetail />} />
        </Routes>
      </main>
      <footer className="site-footer">
        <p>DDBDjango · powered by DynamoDB + OpenSearch</p>
      </footer>
    </BrowserRouter>
  )
}
