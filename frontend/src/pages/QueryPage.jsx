import React, { useEffect, useState } from 'react';
import {
  Search,
  SlidersHorizontal,
  Layers,
  Database,
  FileText,
  Activity,
  CheckCircle2,
  Clock,
  Zap,
  Tag,
  AlertCircle,
  X,
  FileCheck,
  Sparkles,
  ArrowUp,
  ArrowDown,
  Minus,
  Cpu,
  BarChart2,
  Table as TableIcon,
  RefreshCw,
  Copy,
  Check,
  ChevronRight,
} from 'lucide-react';
import { searchApi, documentApi } from '../services/api';
import { useAuth } from '../context/AuthContext';
import Card, { CardHeader, CardTitle, CardDescription, CardContent } from '../components/ui/Card';
import Badge from '../components/ui/Badge';
import Button from '../components/ui/Button';

export default function QueryPage() {
  const { currentTenant } = useAuth();
  const [query, setQuery] = useState('');
  const [strategy, setStrategy] = useState('hybrid');
  const [topK, setTopK] = useState(10);
  const [candidateCount, setCandidateCount] = useState(30);
  const [enableRerank, setEnableRerank] = useState(true);
  const [selectedDocId, setSelectedDocId] = useState('');
  const [availableDocs, setAvailableDocs] = useState([]);
  const [activeTab, setActiveTab] = useState('ranked'); // 'ranked' | 'comparison' | 'telemetry'

  const [isLoading, setIsLoading] = useState(false);
  const [searchResults, setSearchResults] = useState(null);
  const [error, setError] = useState(null);
  const [copiedChunkIdx, setCopiedChunkIdx] = useState(null);

  // Load available documents for filter dropdown
  useEffect(() => {
    if (!currentTenant?.tenant_id) return;
    const fetchDocs = async () => {
      try {
        const res = await documentApi.list({ page: 1, page_size: 100 });
        setAvailableDocs(res.data.items || []);
      } catch (err) {
        // Non-blocking
      }
    };
    fetchDocs();
  }, [currentTenant?.tenant_id]);

  const handleSearchSubmit = async (e) => {
    e?.preventDefault();
    if (!query.trim()) return;

    setIsLoading(true);
    setError(null);

    try {
      let res;
      if (strategy === 'vector') {
        res = await searchApi.vector({
          query: query.trim(),
          top_k: Number(topK),
          document_ids: selectedDocId ? [selectedDocId] : null,
        });
      } else if (strategy === 'bm25') {
        res = await searchApi.bm25({
          query: query.trim(),
          top_k: Number(topK),
          document_ids: selectedDocId ? [selectedDocId] : null,
        });
      } else {
        // Hybrid Search (with optional BGE Cross-Encoder Reranking)
        res = await searchApi.hybrid({
          query: query.trim(),
          top_k: Number(topK),
          document_ids: selectedDocId ? [selectedDocId] : null,
          rerank: Boolean(enableRerank),
          rerank_candidates: Number(candidateCount),
        });
      }
      setSearchResults(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || 'Retrieval search failed.');
      setSearchResults(null);
    } finally {
      setIsLoading(false);
    }
  };

  const getSourceBadge = (source) => {
    switch (source) {
      case 'both':
        return (
          <Badge variant="emerald" size="sm" icon={Zap}>
            Hybrid (Both)
          </Badge>
        );
      case 'vector':
        return (
          <Badge variant="purple" size="sm" icon={Layers}>
            Dense Vector
          </Badge>
        );
      case 'bm25':
        return (
          <Badge variant="cyan" size="sm" icon={FileText}>
            BM25 Lexical
          </Badge>
        );
      default:
        return (
          <Badge variant="neutral" size="sm">
            {source}
          </Badge>
        );
    }
  };

  const getRankDeltaBadge = (originalRank, newRank) => {
    if (!originalRank || !newRank) return null;
    const delta = originalRank - newRank; // positive means promoted up
    if (delta > 0) {
      return (
        <span className="inline-flex items-center gap-0.5 px-2 py-0.5 rounded text-[11px] font-bold bg-emerald-50 text-emerald-700 border border-emerald-200">
          <ArrowUp className="w-3 h-3 text-emerald-600" /> +{delta} (RRF #{originalRank})
        </span>
      );
    } else if (delta < 0) {
      return (
        <span className="inline-flex items-center gap-0.5 px-2 py-0.5 rounded text-[11px] font-bold bg-amber-50 text-amber-700 border border-amber-200">
          <ArrowDown className="w-3 h-3 text-amber-600" /> {delta} (RRF #{originalRank})
        </span>
      );
    } else {
      return (
        <span className="inline-flex items-center gap-0.5 px-2 py-0.5 rounded text-[11px] font-medium bg-slate-100 text-slate-500 border border-slate-200">
          <Minus className="w-3 h-3 text-slate-400" /> Unchanged (RRF #{originalRank})
        </span>
      );
    }
  };

  const copyChunk = (text, idx) => {
    navigator.clipboard.writeText(text);
    setCopiedChunkIdx(idx);
    setTimeout(() => setCopiedChunkIdx(null), 1500);
  };

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-12">
      {/* 1. Page Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-slate-200">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Badge variant="indigo" size="sm">
              Retrieval Engine
            </Badge>
            <span className="text-xs text-slate-400 font-mono">
              BGE-Reranker-Base + BM25 Okapi + Qdrant
            </span>
          </div>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight">
            Search Workbench & Neural Reranker
          </h1>
          <p className="text-xs sm:text-sm text-slate-500 mt-1">
            Interactively inspect semantic dense vector retrieval, lexical keyword search, Reciprocal Rank Fusion, and Cross-Encoder reranking.
          </p>
        </div>

        <Badge variant="emerald" dot size="md">
          Isolated: {currentTenant?.tenant_name}
        </Badge>
      </div>

      {/* Error notification */}
      {error && (
        <div className="p-4 bg-rose-50 border border-rose-200 rounded-xl flex items-center justify-between text-xs text-rose-800 animate-in fade-in">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-rose-600 shrink-0" />
            <span>{error}</span>
          </div>
          <button onClick={() => setError(null)} className="text-rose-600 hover:text-rose-800">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* 2. Search Input & Strategy Configuration */}
      <Card>
        <CardContent className="p-6 space-y-4">
          <form onSubmit={handleSearchSubmit} className="space-y-4">
            <div className="relative flex items-center">
              <Search className="w-5 h-5 text-slate-400 absolute left-4" />
              <input
                type="text"
                placeholder="Enter query or question across your enterprise documents..."
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="w-full pl-12 pr-32 py-3 bg-white border border-slate-300 rounded-xl text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 shadow-xs text-sm sm:text-base transition"
              />
              <div className="absolute right-2">
                <Button
                  type="submit"
                  variant="primary"
                  size="md"
                  disabled={isLoading || !query.trim()}
                  isLoading={isLoading}
                  icon={Search}
                >
                  Retrieve
                </Button>
              </div>
            </div>

            {/* Strategy & Filter Options Bar */}
            <div className="flex flex-wrap items-center justify-between gap-4 pt-3 border-t border-slate-100 text-xs">
              {/* Strategy Switcher */}
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-slate-500 font-semibold uppercase tracking-wider text-[11px]">
                  Strategy:
                </span>
                <div className="inline-flex rounded-lg bg-slate-100 p-0.5 border border-slate-200">
                  <button
                    type="button"
                    onClick={() => setStrategy('hybrid')}
                    className={`px-3 py-1.5 rounded-md font-medium transition ${
                      strategy === 'hybrid'
                        ? 'bg-white text-indigo-700 shadow-xs font-semibold'
                        : 'text-slate-600 hover:text-slate-900'
                    }`}
                  >
                    Hybrid Search
                  </button>
                  <button
                    type="button"
                    onClick={() => setStrategy('vector')}
                    className={`px-3 py-1.5 rounded-md font-medium transition ${
                      strategy === 'vector'
                        ? 'bg-white text-indigo-700 shadow-xs font-semibold'
                        : 'text-slate-600 hover:text-slate-900'
                    }`}
                  >
                    Dense Vector
                  </button>
                  <button
                    type="button"
                    onClick={() => setStrategy('bm25')}
                    className={`px-3 py-1.5 rounded-md font-medium transition ${
                      strategy === 'bm25'
                        ? 'bg-white text-indigo-700 shadow-xs font-semibold'
                        : 'text-slate-600 hover:text-slate-900'
                    }`}
                  >
                    BM25 Lexical
                  </button>
                </div>
              </div>

              {/* Reranker Toggle (for Hybrid) */}
              {strategy === 'hybrid' && (
                <div className="flex items-center gap-2">
                  <label className="flex items-center gap-2 cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={enableRerank}
                      onChange={(e) => setEnableRerank(e.target.checked)}
                      className="w-4 h-4 rounded text-indigo-600 focus:ring-indigo-500 border-slate-300"
                    />
                    <span className="text-slate-700 font-medium flex items-center gap-1">
                      <Sparkles className="w-3.5 h-3.5 text-indigo-600" />
                      BGE Cross-Encoder Reranking
                    </span>
                  </label>
                </div>
              )}

              {/* Document Filter & Top-K */}
              <div className="flex items-center gap-3 flex-wrap">
                <div className="flex items-center gap-1.5">
                  <span className="text-slate-500 font-medium">Document:</span>
                  <select
                    value={selectedDocId}
                    onChange={(e) => setSelectedDocId(e.target.value)}
                    className="text-xs border border-slate-200 rounded-lg px-2.5 py-1 bg-white focus:ring-1 focus:ring-indigo-500 max-w-[150px] truncate"
                  >
                    <option value="">All Documents</option>
                    {availableDocs.map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.filename}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="flex items-center gap-1.5">
                  <span className="text-slate-500 font-medium">Top-K:</span>
                  <input
                    type="number"
                    min="1"
                    max="50"
                    value={topK}
                    onChange={(e) => setTopK(e.target.value)}
                    className="w-14 text-xs border border-slate-200 rounded-lg px-2 py-1 text-center bg-white focus:ring-1 focus:ring-indigo-500"
                  />
                </div>
              </div>
            </div>
          </form>
        </CardContent>
      </Card>

      {/* 3. Search Results Workbench Area */}
      {searchResults ? (
        <div className="space-y-4">
          {/* Results Summary Bar & Tabs */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-200 pb-3">
            <div className="flex items-center gap-4 text-xs font-semibold">
              <button
                onClick={() => setActiveTab('ranked')}
                className={`pb-2 border-b-2 transition flex items-center gap-1.5 ${
                  activeTab === 'ranked'
                    ? 'border-indigo-600 text-indigo-600'
                    : 'border-transparent text-slate-500 hover:text-slate-800'
                }`}
              >
                <span>Ranked Passages</span>
                <span className="px-1.5 py-0.2 bg-slate-100 rounded-full font-mono text-[10px]">
                  {searchResults.results?.length || 0}
                </span>
              </button>

              {searchResults.is_reranked && (
                <button
                  onClick={() => setActiveTab('comparison')}
                  className={`pb-2 border-b-2 transition flex items-center gap-1.5 ${
                    activeTab === 'comparison'
                      ? 'border-indigo-600 text-indigo-600'
                      : 'border-transparent text-slate-500 hover:text-slate-800'
                  }`}
                >
                  <ArrowUpDown className="w-3.5 h-3.5" />
                  <span>Reranking Comparison (RRF vs Neural)</span>
                </button>
              )}

              <button
                onClick={() => setActiveTab('telemetry')}
                className={`pb-2 border-b-2 transition flex items-center gap-1.5 ${
                  activeTab === 'telemetry'
                    ? 'border-indigo-600 text-indigo-600'
                    : 'border-transparent text-slate-500 hover:text-slate-800'
                }`}
              >
                <Clock className="w-3.5 h-3.5" />
                <span>Latency Breakdown ({Math.round(searchResults.total_latency_ms || 0)}ms)</span>
              </button>
            </div>

            <div className="text-xs text-slate-500 font-mono">
              Strategy: <span className="font-semibold text-slate-800">{searchResults.strategy}</span>
            </div>
          </div>

          {/* TAB 1: RANKED PASSAGES */}
          {activeTab === 'ranked' && (
            <div className="space-y-3">
              {searchResults.results?.length === 0 ? (
                <div className="p-12 text-center bg-white border border-slate-200 rounded-xl text-xs text-slate-400">
                  No matching document passages found for this query.
                </div>
              ) : (
                searchResults.results.map((result, idx) => {
                  const score = result.cross_encoder_score ?? result.rrf_score ?? result.score ?? 0;
                  const scoreLabel = result.cross_encoder_score !== undefined
                    ? 'Reranker Score'
                    : result.rrf_score !== undefined
                    ? 'RRF Fusion Score'
                    : 'Similarity Score';

                  return (
                    <Card key={result.chunk_id || idx} className="hover:border-slate-300 transition-colors">
                      <CardContent className="p-4 space-y-2.5">
                        <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                          <div className="flex items-center gap-2 min-w-0">
                            <span className="w-6 h-6 rounded-md bg-indigo-50 text-indigo-700 font-bold flex items-center justify-center font-mono text-xs shrink-0">
                              #{idx + 1}
                            </span>
                            <span className="font-semibold text-slate-900 truncate">
                              {result.document_filename || 'Document'}
                            </span>
                            {result.page_number && (
                              <span className="text-slate-500 font-mono text-[11px]">
                                p.{result.page_number}
                              </span>
                            )}
                            {getSourceBadge(result.source)}
                          </div>

                          <div className="flex items-center gap-3">
                            <div className="text-right text-[11px] font-mono">
                              <span className="text-slate-400 block text-[9px] uppercase font-sans">
                                {scoreLabel}
                              </span>
                              <span className="font-bold text-indigo-600">
                                {score.toFixed(4)}
                              </span>
                            </div>

                            <button
                              onClick={() => copyChunk(result.content, idx)}
                              className="p-1.5 text-slate-400 hover:text-slate-600 rounded hover:bg-slate-100 transition"
                              title="Copy chunk text"
                            >
                              {copiedChunkIdx === idx ? (
                                <Check className="w-3.5 h-3.5 text-emerald-600" />
                              ) : (
                                <Copy className="w-3.5 h-3.5" />
                              )}
                            </button>
                          </div>
                        </div>

                        {/* Chunk Content */}
                        <div className="p-3 bg-slate-50/80 rounded-lg border border-slate-200/80 text-xs text-slate-800 leading-relaxed font-sans whitespace-pre-wrap">
                          {result.content}
                        </div>

                        {/* Chunk Footer */}
                        <div className="flex items-center justify-between text-[11px] text-slate-400 font-mono pt-1">
                          <span>Chunk index: {result.chunk_index ?? 'N/A'}</span>
                          {result.token_count && <span>{result.token_count} tokens</span>}
                        </div>
                      </CardContent>
                    </Card>
                  );
                })
              )}
            </div>
          )}

          {/* TAB 2: BEFORE & AFTER RERANKING COMPARISON */}
          {activeTab === 'comparison' && searchResults.is_reranked && (
            <Card>
              <CardHeader>
                <div>
                  <CardTitle>BGE Cross-Encoder Neural Reranking Matrix</CardTitle>
                  <CardDescription>
                    Demonstrates how cross-attention neural reranking reordered reciprocal rank fusion candidates.
                  </CardDescription>
                </div>
              </CardHeader>
              <CardContent className="p-0">
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm border-collapse">
                    <thead>
                      <tr className="border-b border-slate-200 bg-slate-50/80 text-xs font-semibold text-slate-500 uppercase tracking-wider">
                        <th className="py-3 px-4">New Rank</th>
                        <th className="py-3 px-4">Rank Delta</th>
                        <th className="py-3 px-4">Document</th>
                        <th className="py-3 px-4">Cross-Encoder Score</th>
                        <th className="py-3 px-4">Initial RRF Score</th>
                        <th className="py-3 px-4">Content Preview</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 text-xs">
                      {searchResults.results?.map((r, idx) => (
                        <tr key={idx} className="hover:bg-slate-50/70 transition-colors">
                          <td className="py-3 px-4 font-mono font-bold text-slate-900">
                            #{idx + 1}
                          </td>
                          <td className="py-3 px-4">
                            {getRankDeltaBadge(r.initial_rank, idx + 1)}
                          </td>
                          <td className="py-3 px-4 font-semibold text-slate-800 truncate max-w-[140px]">
                            {r.document_filename}
                          </td>
                          <td className="py-3 px-4 font-mono font-bold text-indigo-600">
                            {r.cross_encoder_score?.toFixed(4) || '—'}
                          </td>
                          <td className="py-3 px-4 font-mono text-slate-500">
                            {r.rrf_score?.toFixed(4) || '—'}
                          </td>
                          <td className="py-3 px-4 text-slate-600 truncate max-w-xs">
                            {r.content?.slice(0, 100)}...
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          )}

          {/* TAB 3: LATENCY TELEMETRY */}
          {activeTab === 'telemetry' && (
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4">
              <Card>
                <CardContent className="p-4 text-xs space-y-1">
                  <span className="text-slate-400 uppercase tracking-wide font-semibold">Total Latency</span>
                  <div className="text-2xl font-extrabold text-slate-900 font-mono">
                    {Math.round(searchResults.total_latency_ms || 0)}ms
                  </div>
                  <p className="text-slate-500 text-[11px]">End-to-end pipeline execution</p>
                </CardContent>
              </Card>

              <Card>
                <CardContent className="p-4 text-xs space-y-1">
                  <span className="text-slate-400 uppercase tracking-wide font-semibold">Vector Search</span>
                  <div className="text-2xl font-extrabold text-purple-600 font-mono">
                    {searchResults.latency_breakdown?.vector_search_ms
                      ? `${Math.round(searchResults.latency_breakdown.vector_search_ms)}ms`
                      : 'N/A'}
                  </div>
                  <p className="text-slate-500 text-[11px]">Qdrant cosine query time</p>
                </CardContent>
              </Card>

              <Card>
                <CardContent className="p-4 text-xs space-y-1">
                  <span className="text-slate-400 uppercase tracking-wide font-semibold">BM25 Search</span>
                  <div className="text-2xl font-extrabold text-cyan-600 font-mono">
                    {searchResults.latency_breakdown?.bm25_search_ms
                      ? `${Math.round(searchResults.latency_breakdown.bm25_search_ms)}ms`
                      : 'N/A'}
                  </div>
                  <p className="text-slate-500 text-[11px]">Lexical inverted index time</p>
                </CardContent>
              </Card>

              <Card>
                <CardContent className="p-4 text-xs space-y-1">
                  <span className="text-slate-400 uppercase tracking-wide font-semibold">Neural Reranker</span>
                  <div className="text-2xl font-extrabold text-indigo-600 font-mono">
                    {searchResults.latency_breakdown?.rerank_ms
                      ? `${Math.round(searchResults.latency_breakdown.rerank_ms)}ms`
                      : 'N/A'}
                  </div>
                  <p className="text-slate-500 text-[11px]">BGE Cross-Encoder inference</p>
                </CardContent>
              </Card>
            </div>
          )}
        </div>
      ) : (
        /* Empty State */
        <Card className="text-center p-12">
          <div className="w-12 h-12 rounded-xl bg-indigo-50 text-indigo-600 flex items-center justify-center mx-auto mb-3">
            <Search className="w-6 h-6" />
          </div>
          <h3 className="text-base font-bold text-slate-800">Ready to search workspace documents</h3>
          <p className="text-xs text-slate-500 mt-1 max-w-md mx-auto leading-relaxed">
            Choose between Hybrid Search, Dense Vector, or BM25 Okapi search. Enter your query above to visualize passage scores, candidate reordering, and latency breakdown.
          </p>
        </Card>
      )}
    </div>
  );
}
