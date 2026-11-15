import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  MessageSquare,
  Plus,
  Send,
  Bot,
  User,
  Copy,
  Check,
  FileText,
  Clock,
  Sparkles,
  ChevronDown,
  ChevronUp,
  AlertCircle,
  Trash2,
  Sliders,
  ExternalLink,
  BookOpen,
  ArrowRight,
  RefreshCw,
  X,
  Layers,
  Zap,
} from 'lucide-react';
import { chatApi, documentApi } from '../services/api';
import { useAuth } from '../context/AuthContext';
import Card, { CardHeader, CardTitle, CardDescription, CardContent } from '../components/ui/Card';
import Badge from '../components/ui/Badge';
import Button from '../components/ui/Button';
import Modal from '../components/ui/Modal';

export default function ChatPage() {
  const { currentTenant, user, accessToken } = useAuth();
  const { sessionId: routeSessionId } = useParams();
  const navigate = useNavigate();

  const [sessions, setSessions] = useState([]);
  const [activeSessionId, setActiveSessionId] = useState(routeSessionId || null);
  const [messages, setMessages] = useState([]);
  const [inputMessage, setInputMessage] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);

  // Document filtering & RAG parameters
  const [availableDocs, setAvailableDocs] = useState([]);
  const [selectedDocId, setSelectedDocId] = useState('');
  const [topK, setTopK] = useState(5);
  const [useStreaming, setUseStreaming] = useState(true);
  const [showSettingsDrawer, setShowSettingsDrawer] = useState(false);

  // Citation inspection drawer
  const [inspectCitation, setInspectCitation] = useState(null);
  const [copiedMessageId, setCopiedMessageId] = useState(null);
  const [copiedCitation, setCopiedCitation] = useState(false);

  // Delete session modal
  const [sessionToDelete, setSessionToDelete] = useState(null);
  const [isDeletingSession, setIsDeletingSession] = useState(false);

  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);

  // Auto-scroll to bottom of chat
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isLoading]);

  // Load available documents for filter selector
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

  const isSendingRef = useRef(false);

  // Load user sessions in current tenant
  const loadSessions = useCallback(async () => {
    const tenantId = currentTenant?.tenant_id || currentTenant?.id || sessionStorage.getItem('active_tenant_id');
    if (!tenantId) return;
    try {
      const res = await chatApi.listSessions();
      setSessions(res.data || []);
      setActiveSessionId((current) => {
        if (!current && res.data && res.data.length > 0) {
          return res.data[0].id;
        }
        return current;
      });
    } catch (err) {
      console.error('Failed to load chat sessions', err);
    }
  }, [currentTenant?.tenant_id, currentTenant?.id]);

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  const loadSessionMessages = useCallback(async (sessionId) => {
    if (!sessionId) {
      setMessages([]);
      return;
    }
    try {
      const res = await chatApi.getSession(sessionId);
      setMessages(res.data.messages || []);
    } catch (err) {
      console.error('Failed to load session messages', err);
    }
  }, []);

  // Load messages when active session changes (unless we are actively sending a prompt)
  useEffect(() => {
    if (isSendingRef.current) {
      return;
    }
    loadSessionMessages(activeSessionId);
  }, [activeSessionId, loadSessionMessages]);

  const handleSelectSession = (sessionId) => {
    if (activeSessionId === sessionId) {
      loadSessionMessages(sessionId);
    } else {
      setActiveSessionId(sessionId);
    }
  };

  // Create new session
  const handleCreateNewSession = async () => {
    try {
      setError(null);
      const res = await chatApi.createSession({
        title: 'New Conversation',
        session_metadata: { source: 'web_ui' },
      });
      setSessions((prev) => [res.data, ...prev]);
      setActiveSessionId(res.data.id);
      setMessages([]);
      inputRef.current?.focus();
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to initialize new conversation.');
    }
  };

  // Delete session
  const handleConfirmDeleteSession = async () => {
    if (!sessionToDelete) return;
    setIsDeletingSession(true);
    try {
      await chatApi.deleteSession(sessionToDelete.id);
      const remaining = sessions.filter((s) => s.id !== sessionToDelete.id);
      setSessions(remaining);
      if (activeSessionId === sessionToDelete.id) {
        setActiveSessionId(remaining[0]?.id || null);
      }
      setSessionToDelete(null);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to delete conversation.');
    } finally {
      setIsDeletingSession(false);
    }
  };

  // Submit message (SSE streaming or synchronous fallback)
  const handleSendMessage = async (e) => {
    e?.preventDefault();
    const prompt = inputMessage.trim();
    if (!prompt || isLoading) return;

    isSendingRef.current = true;
    setIsLoading(true);
    setError(null);

    let currentSessionId = activeSessionId;
    if (!currentSessionId) {
      try {
        const newSessionRes = await chatApi.createSession({
          title: prompt.slice(0, 36) + '...',
          session_metadata: { source: 'web_ui' },
        });
        currentSessionId = newSessionRes.data.id;
        setActiveSessionId(currentSessionId);
        setSessions((prev) => [newSessionRes.data, ...prev]);
      } catch (err) {
        setError('Failed to create chat session.');
        setIsLoading(false);
        isSendingRef.current = false;
        return;
      }
    }

    const userMsg = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: prompt,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInputMessage('');

    const payload = {
      content: prompt,
      question: prompt,
      top_k: Number(topK),
      document_ids: selectedDocId ? [selectedDocId] : null,
    };

    if (useStreaming) {
      const assistantMsgId = `assistant-${Date.now()}`;
      setMessages((prev) => [
        ...prev,
        {
          id: assistantMsgId,
          role: 'assistant',
          content: '',
          citations: [],
          message_metadata: {},
          isStreaming: true,
          created_at: new Date().toISOString(),
        },
      ]);

      try {
        const streamUrl = chatApi.getStreamUrl(currentSessionId);
        const tenantId = currentTenant?.tenant_id || currentTenant?.id || sessionStorage.getItem('active_tenant_id');
        let token = accessToken || sessionStorage.getItem('access_token');

        const buildHeaders = (authToken) => {
          const h = {
            'Content-Type': 'application/json',
          };
          if (tenantId) {
            h['X-Tenant-ID'] = tenantId;
          }
          if (authToken) {
            h['Authorization'] = `Bearer ${authToken}`;
          }
          return h;
        };

        let response = await fetch(streamUrl, {
          method: 'POST',
          headers: buildHeaders(token),
          credentials: 'include',
          body: JSON.stringify(payload),
        });

        // If 401 Unauthorized, attempt background token refresh and retry
        if (response.status === 401) {
          try {
            const refreshRes = await authApi.refresh();
            const newToken = refreshRes.data?.access_token || sessionStorage.getItem('access_token');
            if (newToken) {
              token = newToken;
              response = await fetch(streamUrl, {
                method: 'POST',
                headers: buildHeaders(token),
                credentials: 'include',
                body: JSON.stringify(payload),
              });
            }
          } catch (refreshErr) {
            // Let original response flow through
          }
        }

        if (!response.ok) {
          const errData = await response.json().catch(() => ({}));
          throw new Error(errData.detail || `Server responded with ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let accumulatedTokens = '';
        let finalCitations = [];
        let finalMetrics = {};
        let finalFollowups = [];
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          let currentEvent = 'message';
          for (let i = 0; i < lines.length; i++) {
            const rawLine = lines[i];
            const trimmedLine = rawLine.trim();
            if (!trimmedLine) continue;

            if (trimmedLine.startsWith('event:')) {
              currentEvent = trimmedLine.replace('event:', '').trim();
            } else if (rawLine.startsWith('data:') || trimmedLine.startsWith('data:')) {
              let rawData = rawLine.startsWith('data:') ? rawLine.slice(5) : trimmedLine.slice(5);
              if (rawData.startsWith(' ')) {
                rawData = rawData.slice(1);
              }

              if (currentEvent === 'token') {
                let tokenText = '';
                try {
                  const parsed = JSON.parse(rawData);
                  tokenText = parsed.token !== undefined ? parsed.token : (typeof parsed === 'string' ? parsed : rawData);
                } catch {
                  tokenText = rawData;
                }
                accumulatedTokens += tokenText;
                setMessages((prev) => {
                  const hasMsg = prev.some((m) => m.id === assistantMsgId);
                  if (!hasMsg) {
                    return [
                      ...prev,
                      {
                        id: assistantMsgId,
                        role: 'assistant',
                        content: accumulatedTokens,
                        citations: [],
                        message_metadata: {},
                        isStreaming: true,
                        created_at: new Date().toISOString(),
                      },
                    ];
                  }
                  return prev.map((m) =>
                    m.id === assistantMsgId ? { ...m, content: accumulatedTokens } : m
                  );
                });
              } else if (currentEvent === 'done') {
                try {
                  const parsed = JSON.parse(rawData);
                  finalCitations = parsed.citations || [];
                  finalMetrics = parsed.metrics || {};
                  finalFollowups = parsed.followup_suggestions || [];
                } catch {}
              } else if (currentEvent === 'error') {
                try {
                  const parsedErr = JSON.parse(rawData);
                  setError(parsedErr.error || 'Streaming error');
                } catch {
                  setError(rawData);
                }
              }
            }
          }
        }

        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsgId
              ? {
                  ...m,
                  content: accumulatedTokens,
                  citations: finalCitations,
                  message_metadata: finalMetrics,
                  followup_suggestions: finalFollowups,
                  isStreaming: false,
                }
              : m
          )
        );
        await loadSessions();
        await loadSessionMessages(currentSessionId);
      } catch (err) {
        setError(err.message || 'Error occurred during streaming generation.');
        setMessages((prev) => prev.filter((m) => m.id !== assistantMsgId));
      } finally {
        isSendingRef.current = false;
        setIsLoading(false);
      }
    } else {
      // Synchronous fallback
      try {
        const res = await chatApi.sendMessage(currentSessionId, payload);
        const assistantMsg = {
          id: `resp-${Date.now()}`,
          role: 'assistant',
          content: res.data.answer,
          citations: res.data.citations || [],
          message_metadata: res.data.metrics || {},
          followup_suggestions: res.data.followup_suggestions || [],
          created_at: new Date().toISOString(),
        };
        setMessages((prev) => [...prev, assistantMsg]);
        await loadSessions();
        await loadSessionMessages(currentSessionId);
      } catch (err) {
        setError(err.response?.data?.detail || 'Failed to generate answer.');
      } finally {
        isSendingRef.current = false;
        setIsLoading(false);
      }
    }
  };

  // Helper to copy message text
  const copyMessageText = (id, text) => {
    navigator.clipboard.writeText(text);
    setCopiedMessageId(id);
    setTimeout(() => setCopiedMessageId(null), 2000);
  };

  return (
    <div className="flex h-[calc(100vh-6.5rem)] bg-white border border-slate-200/90 rounded-2xl overflow-hidden shadow-sm">
      {/* 1. Left Sidebar: Conversation History */}
      <div className="w-64 sm:w-72 bg-slate-50/70 border-r border-slate-200/80 flex flex-col shrink-0">
        {/* Header */}
        <div className="p-3.5 border-b border-slate-200/80 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <MessageSquare className="w-4 h-4 text-indigo-600" />
            <h3 className="text-xs font-bold text-slate-900 uppercase tracking-wider">
              Conversations
            </h3>
          </div>
          <Button
            variant="outline"
            size="xs"
            icon={Plus}
            onClick={handleCreateNewSession}
            title="Start new conversation"
          >
            New
          </Button>
        </div>

        {/* Sessions List */}
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {sessions.length === 0 ? (
            <div className="p-8 text-center text-xs text-slate-400">
              <MessageSquare className="w-8 h-8 text-slate-300 mx-auto mb-2" />
              <p className="font-semibold text-slate-600">No chat history</p>
              <p className="mt-0.5">Click "New" above to start your first session.</p>
            </div>
          ) : (
            sessions.map((s) => {
              const isActive = activeSessionId === s.id;
              return (
                <div
                  key={s.id}
                  onClick={() => handleSelectSession(s.id)}
                  className={`group flex items-center justify-between p-2.5 rounded-xl cursor-pointer text-xs transition select-none ${
                    isActive
                      ? 'bg-indigo-50/80 text-indigo-950 font-semibold border border-indigo-200/80 shadow-sm'
                      : 'text-slate-700 hover:bg-slate-100/70 border border-transparent'
                  }`}
                >
                  <div className="truncate mr-2 min-w-0">
                    <p className="truncate text-xs">{s.title || 'Untitled Session'}</p>
                    <p className="text-[10px] text-slate-400 font-mono mt-0.5">
                      {new Date(s.updated_at || s.created_at).toLocaleDateString()}
                    </p>
                  </div>

                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setSessionToDelete(s);
                    }}
                    className="opacity-0 group-hover:opacity-100 p-1 text-slate-400 hover:text-rose-600 rounded transition"
                    title="Delete session"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              );
            })
          )}
        </div>

        {/* Document Filter Quick Status */}
        <div className="p-3 border-t border-slate-200/80 bg-white/60 text-[11px] text-slate-500 flex items-center justify-between">
          <span className="flex items-center gap-1 font-medium">
            <BookOpen className="w-3 h-3 text-indigo-500" />
            {selectedDocId
              ? availableDocs.find((d) => d.id === selectedDocId)?.filename || 'Filtered'
              : 'All Tenant Documents'}
          </span>
          <button
            onClick={() => setShowSettingsDrawer(!showSettingsDrawer)}
            className="text-indigo-600 hover:text-indigo-800 font-semibold"
          >
            Config
          </button>
        </div>
      </div>

      {/* 2. Main Chat Area */}
      <div className="flex-1 flex flex-col min-w-0 bg-white">
        {/* Top Control Bar */}
        <div className="h-14 border-b border-slate-100 px-5 flex items-center justify-between gap-3 bg-white shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            <span className="w-2 h-2 rounded-full bg-emerald-500" />
            <h2 className="text-sm font-bold text-slate-900 truncate">
              {sessions.find((s) => s.id === activeSessionId)?.title || 'Enterprise AI Assistant'}
            </h2>
            <Badge variant="indigo" size="sm" className="hidden sm:inline-flex">
              Grounded RAG
            </Badge>
          </div>

          <div className="flex items-center gap-2">
            {/* Document Filter Dropdown */}
            <select
              value={selectedDocId}
              onChange={(e) => setSelectedDocId(e.target.value)}
              className="text-xs border border-slate-200 rounded-lg px-2 py-1 bg-slate-50 focus:outline-none focus:ring-1 focus:ring-indigo-500 max-w-[140px] sm:max-w-[200px] truncate"
            >
              <option value="">All Documents</option>
              {availableDocs.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.filename}
                </option>
              ))}
            </select>

            {/* Streaming Toggle */}
            <button
              onClick={() => setUseStreaming(!useStreaming)}
              className={`px-2.5 py-1 rounded-lg text-xs font-medium border transition flex items-center gap-1 ${
                useStreaming
                  ? 'bg-indigo-50 text-indigo-700 border-indigo-200'
                  : 'bg-slate-50 text-slate-600 border-slate-200'
              }`}
              title="Toggle Server-Sent Events (SSE) streaming"
            >
              <Zap className="w-3 h-3 text-indigo-600" />
              <span className="hidden sm:inline">Stream</span>
            </button>
          </div>
        </div>

        {/* Error Alert Banner */}
        {error && (
          <div className="mx-4 sm:mx-6 mt-3 p-3 bg-rose-50 border border-rose-200 rounded-xl text-xs text-rose-700 flex items-center justify-between animate-fadeIn">
            <span>{error}</span>
            <button
              onClick={() => setError(null)}
              className="text-rose-500 hover:text-rose-700 font-bold ml-2 text-sm leading-none"
            >
              ×
            </button>
          </div>
        )}

        {/* Message Stream */}
        <div className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-5">
          {messages.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-center max-w-md mx-auto p-6 space-y-4">
              <div className="w-12 h-12 rounded-2xl bg-indigo-50 text-indigo-600 flex items-center justify-center shadow-sm">
                <Sparkles className="w-6 h-6" />
              </div>
              <div>
                <h3 className="text-base font-bold text-slate-900">
                  Ask questions grounded in your documents
                </h3>
                <p className="text-xs text-slate-500 mt-1 leading-relaxed">
                  Hybrid retrieval searches dense vectors in Qdrant and lexical BM25 okapi indexes,
                  reranks candidate passages using BGE Cross-Encoder, and returns verifiable source
                  citations.
                </p>
              </div>

              {/* Sample Starters */}
              <div className="w-full space-y-2 pt-2">
                {[
                  'What are the key findings in our uploaded documents?',
                  'Summarize the compliance and security architecture.',
                  'Extract the main commitments and deadlines.',
                ].map((samplePrompt, idx) => (
                  <button
                    key={idx}
                    onClick={() => {
                      setInputMessage(samplePrompt);
                      inputRef.current?.focus();
                    }}
                    className="w-full text-left p-2.5 bg-slate-50 hover:bg-indigo-50/50 border border-slate-200/80 rounded-xl text-xs text-slate-700 hover:text-indigo-900 transition flex items-center justify-between"
                  >
                    <span>{samplePrompt}</span>
                    <ArrowRight className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((m, idx) => {
              const isUser = m.role === 'user';
              return (
                <div
                  key={m.id || idx}
                  className={`flex gap-3 max-w-4xl ${
                    isUser ? 'ml-auto justify-end' : 'mr-auto justify-start'
                  }`}
                >
                  {!isUser && (
                    <div className="w-8 h-8 rounded-xl bg-indigo-600 text-white flex items-center justify-center shrink-0 shadow-sm mt-0.5">
                      <Bot className="w-4 h-4" />
                    </div>
                  )}

                  <div className={`space-y-2.5 max-w-2xl ${isUser ? 'items-end' : 'items-start'}`}>
                    {/* Message Bubble */}
                    <div
                      className={`p-4 rounded-2xl text-xs sm:text-sm leading-relaxed ${
                        isUser
                          ? 'bg-indigo-600 text-white rounded-tr-sm shadow-sm'
                          : 'bg-slate-50/90 text-slate-800 rounded-tl-sm border border-slate-200/80 shadow-[0_1px_2px_rgba(15,23,42,0.03)]'
                      }`}
                    >
                      <div className="whitespace-pre-wrap">{m.content}</div>

                      {/* Streaming cursor */}
                      {m.isStreaming && (
                        <span className="inline-block w-1.5 h-3 bg-indigo-500 animate-pulse ml-1" />
                      )}
                    </div>

                    {/* Assistant Metadata & Grounded Citations */}
                    {!isUser && (
                      <div className="space-y-2 pl-1">
                        {/* Action buttons & latency pill */}
                        <div className="flex items-center gap-3 text-[11px] text-slate-400 font-mono">
                          <button
                            onClick={() => copyMessageText(m.id, m.content)}
                            className="hover:text-slate-600 flex items-center gap-1 transition"
                            title="Copy response"
                          >
                            {copiedMessageId === m.id ? (
                              <Check className="w-3 h-3 text-emerald-600" />
                            ) : (
                              <Copy className="w-3 h-3" />
                            )}
                            <span>{copiedMessageId === m.id ? 'Copied' : 'Copy'}</span>
                          </button>

                          {m.message_metadata?.total_latency_ms && (
                            <span>• {Math.round(m.message_metadata.total_latency_ms)}ms</span>
                          )}
                          {m.message_metadata?.token_usage?.total_tokens && (
                            <span>• {m.message_metadata.token_usage.total_tokens} tokens</span>
                          )}
                        </div>

                        {/* Grounded Source Citations */}
                        {m.citations && m.citations.length > 0 && (
                          <div className="p-3 bg-indigo-50/40 border border-indigo-100 rounded-xl space-y-2">
                            <span className="text-[10px] font-bold text-indigo-700 uppercase tracking-wider block">
                              Verifiable Source Citations ({m.citations.length})
                            </span>
                            <div className="flex flex-wrap gap-1.5">
                              {m.citations.map((c, cIdx) => (
                                <button
                                  key={cIdx}
                                  onClick={() => setInspectCitation(c)}
                                  className="inline-flex items-center gap-1 px-2.5 py-1 bg-white hover:bg-indigo-50 border border-indigo-200 rounded-lg text-[11px] font-medium text-indigo-900 transition shadow-xs group"
                                  title="Inspect cited source passage"
                                >
                                  <FileText className="w-3 h-3 text-indigo-600" />
                                  <span className="truncate max-w-[140px]">
                                    {c.filename || c.document_title || 'Document'}
                                  </span>
                                  {c.page_number && (
                                    <span className="text-indigo-500 font-mono">p.{c.page_number}</span>
                                  )}
                                </button>
                              ))}
                            </div>
                          </div>
                        )}

                        {/* Follow-up suggestions */}
                        {m.followup_suggestions && m.followup_suggestions.length > 0 && (
                          <div className="flex flex-wrap gap-1.5 pt-1">
                            {m.followup_suggestions.map((suggestion, sIdx) => (
                              <button
                                key={sIdx}
                                onClick={() => {
                                  setInputMessage(suggestion);
                                  inputRef.current?.focus();
                                }}
                                className="px-2.5 py-1 bg-slate-100 hover:bg-indigo-50 text-slate-600 hover:text-indigo-900 border border-slate-200/80 rounded-full text-[11px] transition"
                              >
                                {suggestion}
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>

                  {isUser && (
                    <div className="w-8 h-8 rounded-xl bg-slate-800 text-white flex items-center justify-center shrink-0 shadow-sm mt-0.5">
                      <User className="w-4 h-4" />
                    </div>
                  )}
                </div>
              );
            })
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Input Bar */}
        <div className="p-4 border-t border-slate-100 bg-white">
          <form onSubmit={handleSendMessage} className="max-w-4xl mx-auto space-y-2">
            <div className="relative flex items-center">
              <textarea
                ref={inputRef}
                rows={2}
                value={inputMessage}
                onChange={(e) => setInputMessage(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSendMessage();
                  }
                }}
                placeholder="Ask a question about your documents... (Press Enter to send, Shift+Enter for new line)"
                className="w-full text-xs sm:text-sm pl-4 pr-12 py-3 border border-slate-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 resize-none transition shadow-xs"
              />
              <button
                type="submit"
                disabled={isLoading || !inputMessage.trim()}
                className="absolute right-3 p-2 bg-indigo-600 hover:bg-indigo-700 disabled:bg-slate-200 text-white rounded-lg shadow-sm transition focus:outline-none"
              >
                {isLoading ? (
                  <RefreshCw className="w-4 h-4 animate-spin" />
                ) : (
                  <Send className="w-4 h-4" />
                )}
              </button>
            </div>

            <div className="flex items-center justify-between text-[11px] text-slate-400 px-1">
              <span>Shift + Enter for multiline • Grounded citations returned automatically</span>
              <span>Model: GPT-4o-Mini • Top-K: {topK}</span>
            </div>
          </form>
        </div>
      </div>

      {/* 3. Citation Inspector Modal */}
      <Modal
        isOpen={!!inspectCitation}
        onClose={() => setInspectCitation(null)}
        maxWidth="max-w-xl"
        title="Source Citation Verification"
        description={inspectCitation?.filename || inspectCitation?.document_title || 'Document passage excerpt'}
      >
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 text-xs font-mono">
            <div className="p-2.5 bg-slate-50 rounded-lg border border-slate-200">
              <span className="text-[10px] text-slate-400 uppercase font-sans">Page Number</span>
              <p className="font-semibold text-slate-800 mt-0.5">
                {inspectCitation?.page_number ? `Page ${inspectCitation.page_number}` : 'N/A'}
              </p>
            </div>

            <div className="p-2.5 bg-slate-50 rounded-lg border border-slate-200">
              <span className="text-[10px] text-slate-400 uppercase font-sans">Relevance Score</span>
              <p className="font-semibold text-indigo-600 mt-0.5">
                {inspectCitation?.score !== undefined && inspectCitation?.score !== null
                  ? `${(inspectCitation.score * 100).toFixed(1)}%`
                  : inspectCitation?.relevance_score
                  ? `${(inspectCitation.relevance_score * 100).toFixed(1)}%`
                  : 'Grounded'}
              </p>
            </div>
          </div>

          <div>
            <span className="text-xs font-semibold text-slate-700 uppercase tracking-wide block mb-1">
              Grounding Text Excerpt:
            </span>
            <div className="p-3.5 bg-slate-50 rounded-xl border border-slate-200/90 text-xs text-slate-800 leading-relaxed font-sans whitespace-pre-wrap max-h-60 overflow-y-auto">
              {inspectCitation?.relevant_passage ||
                inspectCitation?.full_passage ||
                inspectCitation?.snippet ||
                inspectCitation?.text ||
                'No text snippet available.'}
            </div>
          </div>

          <div className="flex items-center justify-between pt-3 border-t border-slate-100">
            <Link
              to="/documents"
              onClick={() => setInspectCitation(null)}
              className="text-xs font-semibold text-indigo-600 hover:text-indigo-800 flex items-center gap-1"
            >
              <ExternalLink className="w-3.5 h-3.5" />
              <span>Open in Document Repository</span>
            </Link>

            <Button
              variant="outline"
              size="sm"
              onClick={() => setInspectCitation(null)}
            >
              Close
            </Button>
          </div>
        </div>
      </Modal>

      {/* 4. Delete Session Modal */}
      <Modal
        isOpen={!!sessionToDelete}
        onClose={() => setSessionToDelete(null)}
        title="Delete Conversation"
        description="Are you sure you want to delete this chat session?"
      >
        <div className="space-y-4">
          <p className="text-sm text-slate-600">
            This will permanently delete the conversation titled{' '}
            <span className="font-semibold text-slate-900">"{sessionToDelete?.title}"</span> and all
            associated message history from PostgreSQL.
          </p>

          <div className="flex justify-end gap-2 pt-3 border-t border-slate-100">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setSessionToDelete(null)}
            >
              Cancel
            </Button>
            <Button
              variant="danger"
              size="sm"
              isLoading={isDeletingSession}
              onClick={handleConfirmDeleteSession}
            >
              Delete Conversation
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
