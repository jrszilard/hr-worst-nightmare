import { Routes, Route, Link } from 'react-router-dom'
import ContractFeed from './pages/ContractFeed'
import ProposalReview from './pages/ProposalReview'
import Settings from './pages/Settings'
import History from './pages/History'
import JobsReview from './pages/JobsReview'
import Finalists from './pages/Finalists'

export default function App() {
  return (
    <div className="min-h-screen bg-gray-950">
      <header className="bg-gray-900 border-b border-gray-800 px-6 py-4">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <h1 className="text-2xl font-bold text-gray-100">Contract Finder</h1>
          <nav className="flex gap-4">
            <Link to="/" className="text-gray-400 hover:text-gray-100">Feed</Link>
            <Link to="/settings" className="text-gray-400 hover:text-gray-100">Settings</Link>
            <Link to="/history" className="text-gray-400 hover:text-gray-100">History</Link>
            <Link to="/jobs" className="text-gray-400 hover:text-gray-100">Jobs</Link>
            <Link to="/finalists" className="text-gray-400 hover:text-gray-100">Finalists</Link>
          </nav>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-8">
        <Routes>
          <Route path="/" element={<ContractFeed />} />
          <Route path="/proposal/:id" element={<ProposalReview />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/history" element={<History />} />
          <Route path="/jobs" element={<JobsReview />} />
          <Route path="/finalists" element={<Finalists />} />
        </Routes>
      </main>
    </div>
  )
}
