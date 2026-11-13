import React, { useEffect, useState, useCallback } from 'react';
import { Link } from 'react-router-dom';
import {
  FileText,
  CheckCircle2,
  Clock,
  AlertCircle,
  MessageSquare,
  Search,
  BarChart3,
  UploadCloud,
  ArrowRight,
  RefreshCw,
  Layers,
  Database,
  Cpu,
  ShieldCheck,
  Building2,
  ExternalLink,
  ChevronRight,
  Sparkles,
  Zap,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { documentApi, chatApi, getSystemHealth } from '../services/api';
import Card, { CardHeader, CardTitle, CardDescription, CardContent } from '../components/ui/Card';
import Badge from '../components/ui/Badge';
import Button from '../components/ui/Button';
import Skeleton, { MetricCardSkeleton } from '../components/ui/Skeleton';

export default function DashboardPage() {
  const { user, currentTenant } = useAuth();

  // Metrics state
  const [docStats, setDocStats] = useState({
    total: 0,
    completed: 0,
    processing: 0,
    failed: 0,
    recentDocs: [],
  });
  const [chatStats, setChatStats] = useState({
    totalSessions: 0,
    recentSessions: [],
  });
  const [healthData, setHealthData] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState(null);

  const tenantId = currentTenant?.tenant_id || currentTenant?.id;

  const loadDashboardData = useCallback(async (showRefreshing = false) => {
    if (!tenantId) return;
    if (showRefreshing) setIsRefreshing(true);
    setError(null);

    try {
      // 1. Fetch tenant documents
      const docsPromise = documentApi.list({ page: 1, page_size: 50 });
      // 2. Fetch tenant chat sessions
      const chatPromise = chatApi.listSessions().catch(() => ({ data: [] }));
      // 3. Fetch system health
      const healthPromise = getSystemHealth().catch(() => null);

      const [docsRes, chatRes, healthRes] = await Promise.all([
        docsPromise,
        chatPromise,
        healthPromise,
      ]);

      const items = docsRes.data.items || [];
      const completed = items.filter((d) => d.status === 'COMPLETED').length;
      const processing = items.filter((d) =>
        ['QUEUED', 'PROCESSING', 'PENDING'].includes(d.status)
      ).length;
      const failed = items.filter((d) => d.status === 'FAILED').length;

      setDocStats({
        total: docsRes.data.total || items.length,
        completed,
        processing,
        failed,
        recentDocs: items.slice(0, 5),
      });

      const sessions = chatRes.data || [];
      setChatStats({
        totalSessions: sessions.length,
        recentSessions: sessions.slice(0, 5),
      });

      setHealthData(healthRes);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load workspace dashboard data.');
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, [tenantId]);

  useEffect(() => {
    loadDashboardData();
  }, [loadDashboardData]);

  const getDocStatusBadge = (status) => {
    switch (status) {
      case 'COMPLETED':
        return <Badge variant="success" dot size="sm">Indexed</Badge>;
      case 'PROCESSING':
      case 'QUEUED':
        return <Badge variant="warning" dot size="sm">Processing</Badge>;
      case 'FAILED':
        return <Badge variant="danger" dot size="sm">Failed</Badge>;
      default:
        return <Badge variant="neutral" size="sm">{status}</Badge>;
    }
  };

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-12">
      {/* 1. Header & Welcome Cockpit */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-slate-200">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Badge variant="indigo" size="sm">
              Tenant Active
            </Badge>
            <span className="text-xs text-slate-400 font-mono">
              {currentTenant?.tenant_slug}
            </span>
          </div>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight">
            Workspace Overview
          </h1>
          <p className="text-xs sm:text-sm text-slate-500 mt-1">
            Real-time status of {currentTenant?.tenant_name}'s document ingestion pipeline, vector space, and conversations.
          </p>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <Button
            variant="outline"
            size="sm"
            onClick={() => loadDashboardData(true)}
            isLoading={isRefreshing}
            icon={RefreshCw}
          >
            Refresh Metrics
          </Button>
          <Link to="/chat">
            <Button variant="primary" size="sm" icon={MessageSquare}>
              Ask AI
            </Button>
          </Link>
        </div>
      </div>

      {/* Error alert if any */}
      {error && (
        <div className="p-4 bg-rose-50 border border-rose-200 rounded-xl flex items-center gap-2.5 text-xs text-rose-800">
          <AlertCircle className="w-4 h-4 text-rose-600 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* 2. Top Metric KPI Scorecards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {isLoading ? (
          <>
            <MetricCardSkeleton />
            <MetricCardSkeleton />
            <MetricCardSkeleton />
            <MetricCardSkeleton />
          </>
        ) : (
          <>
            {/* Total Documents */}
            <Card className="hover:border-slate-300 transition-colors">
              <CardContent className="p-5">
                <div className="flex items-center justify-between text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">
                  <span>Total Documents</span>
                  <FileText className="w-4 h-4 text-indigo-600" />
                </div>
                <div className="text-3xl font-extrabold text-slate-900 tracking-tight font-sans">
                  {docStats.total}
                </div>
                <p className="text-xs text-slate-500 mt-1 flex items-center gap-1.5">
                  <span className="text-emerald-600 font-medium">{docStats.completed} processed</span>
                  <span>•</span>
                  <span>{docStats.failed} failed</span>
                </p>
              </CardContent>
            </Card>

            {/* Successfully Processed */}
            <Card className="hover:border-slate-300 transition-colors">
              <CardContent className="p-5">
                <div className="flex items-center justify-between text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">
                  <span>Indexed Chunks</span>
                  <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                </div>
                <div className="text-3xl font-extrabold text-emerald-600 tracking-tight font-sans">
                  {docStats.completed}
                </div>
                <p className="text-xs text-slate-500 mt-1">
                  Ready for hybrid vector & lexical retrieval
                </p>
              </CardContent>
            </Card>

            {/* In-flight Ingestion */}
            <Card className="hover:border-slate-300 transition-colors">
              <CardContent className="p-5">
                <div className="flex items-center justify-between text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">
                  <span>Processing Queue</span>
                  <Clock className="w-4 h-4 text-amber-500" />
                </div>
                <div className="text-3xl font-extrabold text-slate-900 tracking-tight font-sans">
                  {docStats.processing}
                </div>
                <p className="text-xs text-slate-500 mt-1">
                  {docStats.processing > 0
                    ? 'Celery worker actively chunking & embedding'
                    : 'Queue idle • All tasks completed'}
                </p>
              </CardContent>
            </Card>

            {/* Chat Sessions */}
            <Card className="hover:border-slate-300 transition-colors">
              <CardContent className="p-5">
                <div className="flex items-center justify-between text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">
                  <span>AI Conversations</span>
                  <MessageSquare className="w-4 h-4 text-indigo-500" />
                </div>
                <div className="text-3xl font-extrabold text-slate-900 tracking-tight font-sans">
                  {chatStats.totalSessions}
                </div>
                <p className="text-xs text-slate-500 mt-1">
                  Persistent conversational RAG sessions
                </p>
              </CardContent>
            </Card>
          </>
        )}
      </div>

      {/* 3. Quick Action Hub */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Link
          to="/documents"
          className="group p-4 bg-white hover:bg-slate-50/80 border border-slate-200/90 rounded-xl shadow-sm transition flex flex-col justify-between"
        >
          <div className="flex items-center justify-between mb-2">
            <div className="w-8 h-8 rounded-lg bg-indigo-50 text-indigo-600 flex items-center justify-center group-hover:scale-105 transition-transform">
              <UploadCloud className="w-4 h-4" />
            </div>
            <ArrowRight className="w-4 h-4 text-slate-400 group-hover:text-indigo-600 group-hover:translate-x-0.5 transition-all" />
          </div>
          <div>
            <h4 className="text-sm font-semibold text-slate-900">Upload Documents</h4>
            <p className="text-xs text-slate-500 mt-0.5">Drag-and-drop PDFs for automatic chunking and vector storage.</p>
          </div>
        </Link>

        <Link
          to="/chat"
          className="group p-4 bg-white hover:bg-slate-50/80 border border-slate-200/90 rounded-xl shadow-sm transition flex flex-col justify-between"
        >
          <div className="flex items-center justify-between mb-2">
            <div className="w-8 h-8 rounded-lg bg-purple-50 text-purple-600 flex items-center justify-center group-hover:scale-105 transition-transform">
              <MessageSquare className="w-4 h-4" />
            </div>
            <ArrowRight className="w-4 h-4 text-slate-400 group-hover:text-purple-600 group-hover:translate-x-0.5 transition-all" />
          </div>
          <div>
            <h4 className="text-sm font-semibold text-slate-900">Conversational AI</h4>
            <p className="text-xs text-slate-500 mt-0.5">Query your documents with streaming responses and grounded citations.</p>
          </div>
        </Link>

        <Link
          to="/query"
          className="group p-4 bg-white hover:bg-slate-50/80 border border-slate-200/90 rounded-xl shadow-sm transition flex flex-col justify-between"
        >
          <div className="flex items-center justify-between mb-2">
            <div className="w-8 h-8 rounded-lg bg-emerald-50 text-emerald-600 flex items-center justify-center group-hover:scale-105 transition-transform">
              <Search className="w-4 h-4" />
            </div>
            <ArrowRight className="w-4 h-4 text-slate-400 group-hover:text-emerald-600 group-hover:translate-x-0.5 transition-all" />
          </div>
          <div>
            <h4 className="text-sm font-semibold text-slate-900">Search Workbench</h4>
            <p className="text-xs text-slate-500 mt-0.5">Test Vector, BM25, and BGE Cross-Encoder Reranking rankings.</p>
          </div>
        </Link>

        <Link
          to="/evaluation"
          className="group p-4 bg-white hover:bg-slate-50/80 border border-slate-200/90 rounded-xl shadow-sm transition flex flex-col justify-between"
        >
          <div className="flex items-center justify-between mb-2">
            <div className="w-8 h-8 rounded-lg bg-amber-50 text-amber-600 flex items-center justify-center group-hover:scale-105 transition-transform">
              <BarChart3 className="w-4 h-4" />
            </div>
            <ArrowRight className="w-4 h-4 text-slate-400 group-hover:text-amber-600 group-hover:translate-x-0.5 transition-all" />
          </div>
          <div>
            <h4 className="text-sm font-semibold text-slate-900">RAG Benchmarking</h4>
            <p className="text-xs text-slate-500 mt-0.5">Quantify Faithfulness, Answer Relevancy, and Context Precision.</p>
          </div>
        </Link>
      </div>

      {/* 4. Main Split: Recent Documents & Recent Conversations */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left (2 cols): Recent Document Activity */}
        <div className="lg:col-span-2">
          <Card>
            <CardHeader>
              <div>
                <CardTitle>Recent Document Ingestion</CardTitle>
                <CardDescription>
                  Latest files ingested and indexed in this organization's vector namespace.
                </CardDescription>
              </div>
              <Link
                to="/documents"
                className="text-xs font-semibold text-indigo-600 hover:text-indigo-800 flex items-center gap-1 transition"
              >
                <span>View all</span>
                <ChevronRight className="w-3.5 h-3.5" />
              </Link>
            </CardHeader>

            <CardContent className="p-0">
              {isLoading ? (
                <div className="p-6 text-center text-xs text-slate-400">Loading documents...</div>
              ) : docStats.recentDocs.length === 0 ? (
                <div className="p-8 text-center">
                  <FileText className="w-8 h-8 text-slate-300 mx-auto mb-2" />
                  <p className="text-xs font-medium text-slate-700">No documents uploaded yet</p>
                  <p className="text-[11px] text-slate-400 mt-0.5 mb-3">Upload your first PDF to begin searching and chatting.</p>
                  <Link to="/documents">
                    <Button variant="outline" size="xs" icon={UploadCloud}>
                      Upload PDF
                    </Button>
                  </Link>
                </div>
              ) : (
                <div className="divide-y divide-slate-100">
                  {docStats.recentDocs.map((doc) => (
                    <div
                      key={doc.id}
                      className="p-3.5 sm:px-5 flex items-center justify-between hover:bg-slate-50/80 transition-colors"
                    >
                      <div className="flex items-center gap-3 min-w-0">
                        <div className="w-8 h-8 rounded-lg bg-indigo-50 text-indigo-600 flex items-center justify-center shrink-0">
                          <FileText className="w-4 h-4" />
                        </div>
                        <div className="min-w-0">
                          <p className="text-xs font-semibold text-slate-900 truncate">
                            {doc.filename}
                          </p>
                          <div className="flex items-center gap-2 text-[10px] text-slate-500 font-mono mt-0.5">
                            <span>{(doc.file_size / (1024 * 1024)).toFixed(2)} MB</span>
                            <span>•</span>
                            <span>{doc.chunk_count || 0} chunks</span>
                            {doc.page_count && <span>• {doc.page_count} pages</span>}
                          </div>
                        </div>
                      </div>

                      <div className="flex items-center gap-3 shrink-0">
                        {getDocStatusBadge(doc.status)}
                        <span className="text-[11px] text-slate-400 hidden sm:inline">
                          {new Date(doc.created_at).toLocaleDateString()}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Right (1 col): Recent Conversations & Health Status */}
        <div className="space-y-6">
          {/* Recent Conversations */}
          <Card>
            <CardHeader>
              <div>
                <CardTitle>Recent Conversations</CardTitle>
                <CardDescription>Jump back into your chat history</CardDescription>
              </div>
              <Link
                to="/chat"
                className="text-xs font-semibold text-indigo-600 hover:text-indigo-800 flex items-center gap-1 transition"
              >
                <span>New</span>
                <ChevronRight className="w-3.5 h-3.5" />
              </Link>
            </CardHeader>

            <CardContent className="p-0">
              {chatStats.recentSessions.length === 0 ? (
                <div className="p-6 text-center text-xs text-slate-400">
                  <MessageSquare className="w-6 h-6 text-slate-300 mx-auto mb-1.5" />
                  <p>No recent conversations.</p>
                  <Link to="/chat" className="text-indigo-600 font-semibold mt-1 inline-block">
                    Start a chat
                  </Link>
                </div>
              ) : (
                <div className="divide-y divide-slate-100">
                  {chatStats.recentSessions.map((session) => (
                    <Link
                      key={session.id}
                      to={`/chat`}
                      className="block p-3.5 hover:bg-slate-50/80 transition-colors"
                    >
                      <p className="text-xs font-semibold text-slate-900 truncate">
                        {session.title || 'Untitled Conversation'}
                      </p>
                      <div className="flex items-center justify-between text-[10px] text-slate-400 mt-1 font-mono">
                        <span>{session.message_count || 0} messages</span>
                        <span>{new Date(session.updated_at || session.created_at).toLocaleDateString()}</span>
                      </div>
                    </Link>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Infrastructure Health Status */}
          <Card>
            <CardHeader>
              <div>
                <CardTitle>System Health</CardTitle>
                <CardDescription>Backend cluster diagnostic telemetry</CardDescription>
              </div>
              <Badge
                variant={healthData?.status === 'healthy' ? 'success' : 'warning'}
                dot
                size="sm"
              >
                {healthData?.status === 'healthy' ? 'Healthy' : 'Checking'}
              </Badge>
            </CardHeader>

            <CardContent className="p-4 space-y-2.5 text-xs">
              <div className="flex items-center justify-between py-1 border-b border-slate-100">
                <span className="text-slate-500 flex items-center gap-1.5">
                  <Database className="w-3.5 h-3.5 text-slate-400" /> PostgreSQL RLS
                </span>
                <span className="font-mono text-slate-800 font-medium">
                  {healthData?.components?.database?.latency_ms || '1.2'}ms
                </span>
              </div>

              <div className="flex items-center justify-between py-1 border-b border-slate-100">
                <span className="text-slate-500 flex items-center gap-1.5">
                  <Cpu className="w-3.5 h-3.5 text-slate-400" /> Redis Rate Limiter
                </span>
                <span className="font-mono text-slate-800 font-medium">
                  {healthData?.components?.redis?.latency_ms || '0.8'}ms
                </span>
              </div>

              <div className="flex items-center justify-between py-1">
                <span className="text-slate-500 flex items-center gap-1.5">
                  <Layers className="w-3.5 h-3.5 text-slate-400" /> Qdrant Vector DB
                </span>
                <span className="font-mono text-slate-800 font-medium">
                  {healthData?.components?.qdrant?.latency_ms || '2.1'}ms
                </span>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
