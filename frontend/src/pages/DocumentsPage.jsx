import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  FileText,
  UploadCloud,
  RefreshCw,
  Trash2,
  CheckCircle2,
  Clock,
  AlertCircle,
  Search,
  ChevronRight,
  Layers,
  Database,
  Eye,
  X,
  Copy,
  Check,
  Download,
  Filter,
  ArrowUpDown,
  BookOpen,
  FileCheck,
} from 'lucide-react';
import { documentApi } from '../services/api';
import { useAuth } from '../context/AuthContext';
import Card, { CardHeader, CardTitle, CardDescription, CardContent } from '../components/ui/Card';
import Badge from '../components/ui/Badge';
import Button from '../components/ui/Button';
import Modal from '../components/ui/Modal';
import Skeleton, { TableRowSkeleton } from '../components/ui/Skeleton';

export default function DocumentsPage() {
  const { currentTenant } = useAuth();
  const [documents, setDocuments] = useState([]);
  const [totalCount, setTotalCount] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [sortBy, setSortBy] = useState('date_desc');
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [successMessage, setSuccessMessage] = useState(null);

  // Upload state
  const [isUploading, setIsUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [selectedFile, setSelectedFile] = useState(null);
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef(null);

  // Detail & Preview Modal state
  const [detailDoc, setDetailDoc] = useState(null);
  const [isLoadingDetail, setIsLoadingDetail] = useState(false);
  const [detailActiveTab, setDetailActiveTab] = useState('preview'); // 'preview' | 'chunks' | 'metadata'
  const [pdfBlobUrl, setPdfBlobUrl] = useState(null);
  const [chunkSearch, setChunkSearch] = useState('');
  const [copiedChunkIdx, setCopiedChunkIdx] = useState(null);

  // Delete candidate modal
  const [deleteCandidate, setDeleteCandidate] = useState(null);
  const [isDeleting, setIsDeleting] = useState(false);

  const isTenantAdmin = currentTenant?.role === 'OWNER' || currentTenant?.role === 'ADMIN';

  // Fetch documents for active tenant
  const fetchDocuments = useCallback(
    async (isBackground = false) => {
      if (!currentTenant?.tenant_id) return;
      if (!isBackground) setIsLoading(true);
      setError(null);
      try {
        const res = await documentApi.list({
          page,
          page_size: 20,
          search: search.trim() || undefined,
          status: statusFilter || undefined,
        });
        setDocuments(res.data.items || []);
        setTotalCount(res.data.total || 0);
      } catch (err) {
        if (!isBackground) {
          setError(err.response?.data?.detail || 'Failed to load organization documents.');
        }
      } finally {
        if (!isBackground) setIsLoading(false);
      }
    },
    [currentTenant?.tenant_id, page, search, statusFilter]
  );

  useEffect(() => {
    fetchDocuments();
  }, [fetchDocuments]);

  // Live polling for transient processing states
  useEffect(() => {
    const hasActiveJobs = documents.some((doc) =>
      ['QUEUED', 'PROCESSING', 'PENDING'].includes(doc.status)
    );
    if (!hasActiveJobs) return;

    const intervalId = setInterval(() => {
      fetchDocuments(true);
    }, 2500);

    return () => clearInterval(intervalId);
  }, [documents, fetchDocuments]);

  // Clean up PDF blob URL
  useEffect(() => {
    return () => {
      if (pdfBlobUrl) URL.revokeObjectURL(pdfBlobUrl);
    };
  }, [pdfBlobUrl]);

  // Drag and drop handlers
  const handleDrag = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  };

  const validateAndSetFile = (file) => {
    setError(null);
    setSuccessMessage(null);
    if (!file) return;

    if (!file.name.toLowerCase().endsWith('.pdf')) {
      setError('Only valid PDF documents (.pdf) are supported.');
      return;
    }

    const maxSize = 25 * 1024 * 1024; // 25 MB
    if (file.size > maxSize) {
      setError(`File size (${(file.size / (1024 * 1024)).toFixed(1)} MB) exceeds 25 MB limit.`);
      return;
    }

    setSelectedFile(file);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      validateAndSetFile(e.dataTransfer.files[0]);
    }
  };

  const handleFileChange = (e) => {
    if (e.target.files && e.target.files[0]) {
      validateAndSetFile(e.target.files[0]);
    }
  };

  // Upload handler
  const handleUploadSubmit = async (e) => {
    e.preventDefault();
    if (!selectedFile) return;

    setIsUploading(true);
    setUploadProgress(0);
    setError(null);
    setSuccessMessage(null);

    try {
      const res = await documentApi.upload(selectedFile, (progressEvent) => {
        const percentCompleted = Math.round(
          (progressEvent.loaded * 100) / (progressEvent.total || selectedFile.size)
        );
        setUploadProgress(percentCompleted);
      });

      setSuccessMessage(`Document "${res.data.filename}" queued for asynchronous processing.`);
      setSelectedFile(null);
      if (fileInputRef.current) fileInputRef.current.value = '';
      fetchDocuments();
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to upload document.');
    } finally {
      setIsUploading(false);
    }
  };

  // Open detail & PDF preview view
  const handleOpenDetail = async (docId) => {
    setIsLoadingDetail(true);
    setDetailDoc(null);
    if (pdfBlobUrl) {
      URL.revokeObjectURL(pdfBlobUrl);
      setPdfBlobUrl(null);
    }

    try {
      // Fetch metadata and chunks
      const res = await documentApi.getDetail(docId);
      setDetailDoc(res.data);

      // Attempt to fetch raw PDF blob for interactive preview
      try {
        const blobRes = await documentApi.getFileBlob(docId);
        const url = URL.createObjectURL(new Blob([blobRes.data], { type: 'application/pdf' }));
        setPdfBlobUrl(url);
      } catch (fileErr) {
        console.warn('PDF file preview fetch error:', fileErr);
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load document details.');
    } finally {
      setIsLoadingDetail(false);
    }
  };

  // Delete document
  const handleConfirmDelete = async () => {
    if (!deleteCandidate) return;
    setIsDeleting(true);
    setError(null);
    try {
      await documentApi.delete(deleteCandidate.id);
      setSuccessMessage(
        `Document "${deleteCandidate.filename}" and its vector indices were deleted.`
      );
      setDeleteCandidate(null);
      if (detailDoc?.id === deleteCandidate.id) setDetailDoc(null);
      fetchDocuments();
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to delete document.');
    } finally {
      setIsDeleting(false);
    }
  };

  const formatBytes = (bytes) => {
    if (!bytes || bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
  };

  const getStatusBadge = (status) => {
    switch (status) {
      case 'COMPLETED':
        return (
          <Badge variant="success" dot size="sm">
            Indexed
          </Badge>
        );
      case 'PROCESSING':
        return (
          <Badge variant="warning" dot size="sm" className="animate-pulse">
            Vectorizing
          </Badge>
        );
      case 'QUEUED':
        return (
          <Badge variant="cyan" dot size="sm">
            Queued
          </Badge>
        );
      case 'FAILED':
        return (
          <Badge variant="danger" dot size="sm">
            Failed
          </Badge>
        );
      case 'DELETING':
        return (
          <Badge variant="neutral" dot size="sm">
            Deleting
          </Badge>
        );
      default:
        return (
          <Badge variant="neutral" size="sm">
            {status}
          </Badge>
        );
    }
  };

  // Sort documents client-side if needed
  const sortedDocuments = [...documents].sort((a, b) => {
    if (sortBy === 'name') return a.filename.localeCompare(b.filename);
    if (sortBy === 'size') return b.file_size - a.file_size;
    if (sortBy === 'chunks') return (b.chunk_count || 0) - (a.chunk_count || 0);
    return new Date(b.created_at) - new Date(a.created_at);
  });

  // Filter chunks in detail view
  const filteredChunks = (detailDoc?.chunks || []).filter(
    (c) =>
      !chunkSearch.trim() ||
      c.content?.toLowerCase().includes(chunkSearch.toLowerCase()) ||
      String(c.page_number).includes(chunkSearch)
  );

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-12">
      {/* 1. Page Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-slate-200">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Badge variant="indigo" size="sm">
              Document Pipeline
            </Badge>
            <span className="text-xs text-slate-400 font-mono">
              BGE-Small Embeddings (384-dim)
            </span>
          </div>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight">
            Document Repository & Ingestion
          </h1>
          <p className="text-xs sm:text-sm text-slate-500 mt-1">
            Upload PDFs for automatic text extraction, chunking, dense vector indexing in Qdrant, and BM25 indexing.
          </p>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <Button
            variant="outline"
            size="sm"
            onClick={() => fetchDocuments()}
            isLoading={isLoading}
            icon={RefreshCw}
          >
            Refresh
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => fileInputRef.current?.click()}
            icon={UploadCloud}
          >
            Upload PDF
          </Button>
        </div>
      </div>

      {/* Notifications */}
      {successMessage && (
        <div className="p-4 bg-emerald-50 border border-emerald-200 rounded-xl flex items-center justify-between text-xs text-emerald-800 animate-in fade-in">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
            <span>{successMessage}</span>
          </div>
          <button onClick={() => setSuccessMessage(null)} className="text-emerald-600 hover:text-emerald-800">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}
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

      {/* 2. Drag & Drop Upload Zone */}
      <Card>
        <CardContent className="p-6">
          <form
            onSubmit={handleUploadSubmit}
            onDragEnter={handleDrag}
            onDragOver={handleDrag}
            onDragLeave={handleDrag}
            onDrop={handleDrop}
            className={`border-2 border-dashed rounded-xl p-8 text-center transition-all ${
              dragActive
                ? 'border-indigo-500 bg-indigo-50/50 scale-[0.99]'
                : selectedFile
                ? 'border-emerald-400 bg-emerald-50/20'
                : 'border-slate-200 hover:border-slate-300 bg-slate-50/50'
            }`}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,application/pdf"
              className="hidden"
              onChange={handleFileChange}
            />

            <div className="flex flex-col items-center justify-center max-w-md mx-auto">
              <div
                className={`w-12 h-12 rounded-xl flex items-center justify-center mb-3 transition-colors ${
                  selectedFile
                    ? 'bg-emerald-100 text-emerald-700'
                    : 'bg-indigo-50 text-indigo-600'
                }`}
              >
                {selectedFile ? (
                  <FileCheck className="w-6 h-6" />
                ) : (
                  <UploadCloud className="w-6 h-6" />
                )}
              </div>

              {selectedFile ? (
                <div className="space-y-1">
                  <p className="text-sm font-semibold text-slate-900 truncate">
                    {selectedFile.name}
                  </p>
                  <p className="text-xs text-slate-500 font-mono">
                    {formatBytes(selectedFile.size)} • PDF Ready for Ingestion
                  </p>
                </div>
              ) : (
                <div className="space-y-1">
                  <p className="text-sm font-semibold text-slate-800">
                    Drag and drop your PDF here, or{' '}
                    <button
                      type="button"
                      onClick={() => fileInputRef.current?.click()}
                      className="text-indigo-600 hover:text-indigo-700 underline font-medium focus:outline-none"
                    >
                      browse files
                    </button>
                  </p>
                  <p className="text-xs text-slate-400">
                    PDF documents up to 25 MB • Automatically extracted and vectorized
                  </p>
                </div>
              )}

              {/* Upload Progress Bar */}
              {isUploading && (
                <div className="w-full max-w-xs mt-4 space-y-1.5">
                  <div className="flex items-center justify-between text-[11px] text-slate-600">
                    <span>Uploading file...</span>
                    <span className="font-mono">{uploadProgress}%</span>
                  </div>
                  <div className="w-full h-1.5 bg-slate-200 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-indigo-600 transition-all duration-200 rounded-full"
                      style={{ width: `${uploadProgress}%` }}
                    />
                  </div>
                </div>
              )}

              {/* Action Buttons */}
              {selectedFile && !isUploading && (
                <div className="flex items-center gap-2 mt-4">
                  <Button
                    type="submit"
                    variant="primary"
                    size="sm"
                    isLoading={isUploading}
                    icon={UploadCloud}
                  >
                    Start Ingestion
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setSelectedFile(null)}
                  >
                    Cancel
                  </Button>
                </div>
              )}
            </div>
          </form>
        </CardContent>
      </Card>

      {/* 3. Document Repository Table */}
      <Card>
        {/* Table Controls Bar */}
        <div className="p-4 border-b border-slate-100 flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-slate-50/50">
          <div className="flex items-center gap-2 flex-1 max-w-md">
            <div className="relative w-full">
              <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                placeholder="Search documents by filename..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full text-xs pl-9 pr-3 py-2 border border-slate-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500"
              />
            </div>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            {/* Status Filter */}
            <div className="flex items-center gap-1.5 text-xs text-slate-600">
              <Filter className="w-3.5 h-3.5 text-slate-400" />
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="text-xs border border-slate-200 rounded-lg px-2.5 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
              >
                <option value="">All Statuses</option>
                <option value="COMPLETED">Indexed</option>
                <option value="PROCESSING">Processing</option>
                <option value="QUEUED">Queued</option>
                <option value="FAILED">Failed</option>
              </select>
            </div>

            {/* Sort Order */}
            <div className="flex items-center gap-1.5 text-xs text-slate-600">
              <ArrowUpDown className="w-3.5 h-3.5 text-slate-400" />
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value)}
                className="text-xs border border-slate-200 rounded-lg px-2.5 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
              >
                <option value="date_desc">Newest First</option>
                <option value="date_asc">Oldest First</option>
                <option value="name">Filename (A-Z)</option>
                <option value="size">File Size</option>
                <option value="chunks">Chunk Count</option>
              </select>
            </div>
          </div>
        </div>

        {/* Table Content */}
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm border-collapse">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50/80 text-xs font-semibold text-slate-500 uppercase tracking-wider">
                <th className="py-3 px-4">Document</th>
                <th className="py-3 px-4">Status</th>
                <th className="py-3 px-4">Size</th>
                <th className="py-3 px-4">Pages</th>
                <th className="py-3 px-4">Chunks</th>
                <th className="py-3 px-4">Uploaded</th>
                <th className="py-3 px-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {isLoading ? (
                <>
                  <TableRowSkeleton columns={7} />
                  <TableRowSkeleton columns={7} />
                  <TableRowSkeleton columns={7} />
                </>
              ) : sortedDocuments.length === 0 ? (
                <tr>
                  <td colSpan={7} className="p-12 text-center text-slate-400 text-xs">
                    <FileText className="w-8 h-8 text-slate-300 mx-auto mb-2" />
                    <p className="font-semibold text-slate-600">No documents found</p>
                    <p className="text-slate-400 mt-0.5">
                      {search || statusFilter
                        ? 'Try clearing your search filters above.'
                        : 'Upload a PDF document to begin testing RAG retrieval.'}
                    </p>
                  </td>
                </tr>
              ) : (
                sortedDocuments.map((doc) => (
                  <tr key={doc.id} className="hover:bg-slate-50/70 transition-colors">
                    {/* Filename */}
                    <td className="py-3.5 px-4 font-semibold text-slate-900">
                      <div className="flex items-center gap-3">
                        <div className="w-7 h-7 rounded-lg bg-indigo-50 text-indigo-600 flex items-center justify-center shrink-0">
                          <FileText className="w-4 h-4" />
                        </div>
                        <span className="truncate max-w-xs sm:max-w-md block" title={doc.filename}>
                          {doc.filename}
                        </span>
                      </div>
                    </td>

                    {/* Status */}
                    <td className="py-3.5 px-4">{getStatusBadge(doc.status)}</td>

                    {/* Size */}
                    <td className="py-3.5 px-4 font-mono text-xs text-slate-500">
                      {formatBytes(doc.file_size)}
                    </td>

                    {/* Pages */}
                    <td className="py-3.5 px-4 font-mono text-xs text-slate-600">
                      {doc.page_count ? `${doc.page_count} pp` : '—'}
                    </td>

                    {/* Chunks */}
                    <td className="py-3.5 px-4 font-mono text-xs text-indigo-600 font-semibold">
                      {doc.chunk_count || 0}
                    </td>

                    {/* Date */}
                    <td className="py-3.5 px-4 text-xs text-slate-500 font-mono">
                      {new Date(doc.created_at).toLocaleDateString()}
                    </td>

                    {/* Actions */}
                    <td className="py-3.5 px-4 text-right">
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="xs"
                          icon={Eye}
                          onClick={() => handleOpenDetail(doc.id)}
                          title="Inspect chunks and preview PDF"
                        >
                          View
                        </Button>

                        {isTenantAdmin && (
                          <Button
                            variant="ghost"
                            size="xs"
                            icon={Trash2}
                            onClick={() => setDeleteCandidate(doc)}
                            className="text-slate-400 hover:text-rose-600 hover:bg-rose-50"
                            title="Delete document and vector embeddings"
                          />
                        )}
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination bar */}
        {totalCount > 20 && (
          <div className="p-4 border-t border-slate-100 flex items-center justify-between text-xs text-slate-500">
            <span>
              Showing {sortedDocuments.length} of {totalCount} documents
            </span>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="xs"
                disabled={page <= 1}
                onClick={() => setPage(page - 1)}
              >
                Previous
              </Button>
              <span className="font-mono px-2">Page {page}</span>
              <Button
                variant="outline"
                size="xs"
                disabled={page * 20 >= totalCount}
                onClick={() => setPage(page + 1)}
              >
                Next
              </Button>
            </div>
          </div>
        )}
      </Card>

      {/* 4. Document Detail & PDF Preview Modal */}
      <Modal
        isOpen={!!detailDoc}
        onClose={() => setDetailDoc(null)}
        maxWidth="max-w-5xl"
        title={detailDoc?.filename || 'Document Inspection'}
        description={`Document ID: ${detailDoc?.id || ''}`}
      >
        <div className="space-y-4">
          {/* Detail Tab Strip */}
          <div className="flex border-b border-slate-200 gap-4 text-xs font-semibold">
            <button
              onClick={() => setDetailActiveTab('preview')}
              className={`pb-2.5 border-b-2 transition ${
                detailActiveTab === 'preview'
                  ? 'border-indigo-600 text-indigo-600'
                  : 'border-transparent text-slate-500 hover:text-slate-800'
              }`}
            >
              PDF Document Viewer
            </button>
            <button
              onClick={() => setDetailActiveTab('chunks')}
              className={`pb-2.5 border-b-2 transition flex items-center gap-1.5 ${
                detailActiveTab === 'chunks'
                  ? 'border-indigo-600 text-indigo-600'
                  : 'border-transparent text-slate-500 hover:text-slate-800'
              }`}
            >
              <span>Extracted Chunks</span>
              <span className="px-1.5 py-0.2 bg-slate-100 rounded text-[10px] font-mono">
                {detailDoc?.chunks?.length || 0}
              </span>
            </button>
            <button
              onClick={() => setDetailActiveTab('metadata')}
              className={`pb-2.5 border-b-2 transition ${
                detailActiveTab === 'metadata'
                  ? 'border-indigo-600 text-indigo-600'
                  : 'border-transparent text-slate-500 hover:text-slate-800'
              }`}
            >
              System Metadata & Ingestion
            </button>
          </div>

          {/* TAB 1: PDF PREVIEW */}
          {detailActiveTab === 'preview' && (
            <div className="space-y-3">
              {pdfBlobUrl ? (
                <div className="rounded-xl border border-slate-200 overflow-hidden bg-slate-100 shadow-inner">
                  <div className="bg-slate-50 p-2.5 border-b border-slate-200 flex items-center justify-between text-xs text-slate-600">
                    <span className="font-medium">
                      Pages: {detailDoc?.page_count || 1} • Size: {formatBytes(detailDoc?.file_size)}
                    </span>
                    <a
                      href={pdfBlobUrl}
                      download={detailDoc?.filename}
                      className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium bg-white hover:bg-slate-100 border border-slate-200 rounded-md transition"
                    >
                      <Download className="w-3.5 h-3.5 text-slate-500" />
                      <span>Download PDF</span>
                    </a>
                  </div>
                  <iframe
                    src={pdfBlobUrl}
                    className="w-full h-[520px] bg-white"
                    title="PDF Viewer"
                  />
                </div>
              ) : (
                <div className="p-12 text-center bg-slate-50 border border-slate-200 rounded-xl space-y-2">
                  <BookOpen className="w-8 h-8 text-slate-300 mx-auto" />
                  <p className="text-sm font-semibold text-slate-700">Preview unavailable</p>
                  <p className="text-xs text-slate-400">
                    The document file can still be queried through vector search and the AI assistant.
                  </p>
                </div>
              )}
            </div>
          )}

          {/* TAB 2: CHUNKS INSPECTOR */}
          {detailActiveTab === 'chunks' && (
            <div className="space-y-3">
              <div className="flex items-center justify-between gap-3">
                <input
                  type="text"
                  placeholder="Filter chunks by keyword or page number..."
                  value={chunkSearch}
                  onChange={(e) => setChunkSearch(e.target.value)}
                  className="w-full text-xs px-3 py-2 border border-slate-200 rounded-lg focus:ring-2 focus:ring-indigo-500/20"
                />
                <span className="text-xs text-slate-400 font-mono shrink-0">
                  {filteredChunks.length} chunks
                </span>
              </div>

              <div className="max-h-[480px] overflow-y-auto space-y-2.5 pr-1">
                {filteredChunks.map((chunk, idx) => (
                  <div
                    key={chunk.id || idx}
                    className="p-3 bg-slate-50 hover:bg-slate-100/60 rounded-xl border border-slate-200/90 transition text-xs space-y-1.5"
                  >
                    <div className="flex items-center justify-between text-[11px] text-slate-500 font-mono">
                      <span className="font-bold text-indigo-700">
                        Chunk #{chunk.chunk_index + 1} • Page {chunk.page_number}
                      </span>
                      <div className="flex items-center gap-2">
                        <span>{chunk.token_count || 0} tokens</span>
                        <button
                          onClick={() => {
                            navigator.clipboard.writeText(chunk.content);
                            setCopiedChunkIdx(idx);
                            setTimeout(() => setCopiedChunkIdx(null), 1500);
                          }}
                          className="text-slate-400 hover:text-slate-600 p-1"
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
                    <p className="text-slate-800 leading-relaxed font-sans text-xs whitespace-pre-wrap">
                      {chunk.content}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* TAB 3: METADATA & INGESTION TELEMETRY */}
          {detailActiveTab === 'metadata' && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
              <div className="p-3 bg-slate-50 rounded-lg border border-slate-200 space-y-1">
                <span className="text-slate-400 uppercase tracking-wide font-semibold">
                  MIME Type
                </span>
                <p className="font-mono text-slate-800">{detailDoc?.mime_type || 'application/pdf'}</p>
              </div>

              <div className="p-3 bg-slate-50 rounded-lg border border-slate-200 space-y-1">
                <span className="text-slate-400 uppercase tracking-wide font-semibold">
                  Storage Path
                </span>
                <p className="font-mono text-slate-800 truncate" title={detailDoc?.storage_path}>
                  {detailDoc?.storage_path}
                </p>
              </div>

              <div className="p-3 bg-slate-50 rounded-lg border border-slate-200 space-y-1">
                <span className="text-slate-400 uppercase tracking-wide font-semibold">
                  SHA-256 Checksum
                </span>
                <p className="font-mono text-slate-800 truncate" title={detailDoc?.checksum}>
                  {detailDoc?.checksum}
                </p>
              </div>

              <div className="p-3 bg-slate-50 rounded-lg border border-slate-200 space-y-1">
                <span className="text-slate-400 uppercase tracking-wide font-semibold">
                  Vector Partition (Qdrant)
                </span>
                <p className="font-mono text-indigo-700 font-semibold">
                  tenant_id: {currentTenant?.tenant_id}
                </p>
              </div>
            </div>
          )}

          <div className="flex justify-end pt-3 border-t border-slate-100">
            <Button variant="outline" size="sm" onClick={() => setDetailDoc(null)}>
              Close
            </Button>
          </div>
        </div>
      </Modal>

      {/* 5. Delete Confirmation Modal */}
      <Modal
        isOpen={!!deleteCandidate}
        onClose={() => setDeleteCandidate(null)}
        title="Delete Document"
        description="Are you sure you want to permanently delete this document?"
      >
        <div className="space-y-4">
          <p className="text-sm text-slate-600">
            This will permanently remove{' '}
            <span className="font-semibold text-slate-900">{deleteCandidate?.filename}</span>,
            delete all vector points from Qdrant, remove its lexical BM25 entries, and cascade
            delete relational chunk records in PostgreSQL.
          </p>

          <div className="flex justify-end gap-2 pt-3 border-t border-slate-100">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setDeleteCandidate(null)}
            >
              Cancel
            </Button>
            <Button
              variant="danger"
              size="sm"
              isLoading={isDeleting}
              onClick={handleConfirmDelete}
            >
              Confirm Deletion
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
