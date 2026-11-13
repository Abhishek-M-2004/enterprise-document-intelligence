import React, { useEffect, useState } from 'react';
import {
  Activity,
  AlertCircle,
  BarChart3,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Database,
  Download,
  FileSpreadsheet,
  FileText,
  Flame,
  Layers,
  Play,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
  Zap,
} from 'lucide-react';
import { evaluationApi } from '../services/api';

export default function EvaluationPage() {
  const [datasets, setDatasets] = useState([]);
  const [selectedDatasetId, setSelectedDatasetId] = useState('');
  const [samples, setSamples] = useState([]);
  const [runs, setRuns] = useState([]);
  const [activeRun, setActiveRun] = useState(null);
  const [runResults, setRunResults] = useState([]);
  const [comparisonData, setComparisonData] = useState(null);

  // UI state
  const [isLoading, setIsLoading] = useState(false);
  const [isComparing, setIsComparing] = useState(false);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState('overview'); // 'overview' | 'comparison' | 'samples' | 'history'
  const [expandedSampleId, setExpandedSampleId] = useState(null);

  // Form states
  const [selectedStrategy, setSelectedStrategy] = useState('hybrid_rerank');
  const [topK, setTopK] = useState(5);
  const [newDatasetName, setNewDatasetName] = useState('');
  const [showNewDatasetModal, setShowNewDatasetModal] = useState(false);
  const [newQuestion, setNewQuestion] = useState('');
  const [newGroundTruth, setNewGroundTruth] = useState('');
  const [showAddSampleModal, setShowAddSampleModal] = useState(false);

  // 1. Load initial datasets & runs
  useEffect(() => {
    loadDatasets();
    loadRuns();
  }, []);

  // 2. Load samples when dataset selection changes
  useEffect(() => {
    if (selectedDatasetId) {
      loadSamples(selectedDatasetId);
    }
  }, [selectedDatasetId]);

  const loadDatasets = async () => {
    try {
      setError(null);
      const res = await evaluationApi.listDatasets();
      setDatasets(res.data);
      if (res.data.length > 0 && !selectedDatasetId) {
        setSelectedDatasetId(res.data[0].id);
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load datasets.');
    }
  };

  const loadSamples = async (datasetId) => {
    try {
      const res = await evaluationApi.listSamples(datasetId);
      setSamples(res.data);
    } catch (err) {
      console.error('Failed to load samples:', err);
    }
  };

  const loadRuns = async () => {
    try {
      const res = await evaluationApi.listRuns();
      setRuns(res.data);
      if (res.data.length > 0 && !activeRun) {
        selectRun(res.data[0]);
      }
    } catch (err) {
      console.error('Failed to load runs:', err);
    }
  };

  const selectRun = async (run) => {
    setActiveRun(run);
    try {
      const res = await evaluationApi.getRunResults(run.id);
      setRunResults(res.data);
    } catch (err) {
      console.error('Failed to load run results:', err);
    }
  };

  const handleCreateSyntheticDataset = async () => {
    try {
      setIsLoading(true);
      setError(null);
      const res = await evaluationApi.createSyntheticDataset({ name: 'Standard RAG Benchmark' });
      await loadDatasets();
      setSelectedDatasetId(res.data.id);
      setActiveTab('samples');
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to create synthetic dataset.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleCreateDataset = async (e) => {
    e.preventDefault();
    if (!newDatasetName.trim()) return;
    try {
      setIsLoading(true);
      const res = await evaluationApi.createDataset({ name: newDatasetName.trim() });
      setNewDatasetName('');
      setShowNewDatasetModal(false);
      await loadDatasets();
      setSelectedDatasetId(res.data.id);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to create dataset.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleAddSample = async (e) => {
    e.preventDefault();
    if (!newQuestion.trim() || !selectedDatasetId) return;
    try {
      setIsLoading(true);
      await evaluationApi.addSample(selectedDatasetId, {
        question: newQuestion.trim(),
        ground_truth: newGroundTruth.trim() || null,
      });
      setNewQuestion('');
      setNewGroundTruth('');
      setShowAddSampleModal(false);
      await loadSamples(selectedDatasetId);
      await loadDatasets();
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to add sample.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleRunEvaluation = async () => {
    if (!selectedDatasetId) return;
    try {
      setIsLoading(true);
      setError(null);
      const res = await evaluationApi.createRun({
        dataset_id: selectedDatasetId,
        retrieval_strategy: selectedStrategy,
        top_k: Number(topK),
        candidate_top_k: 20,
      });
      await loadRuns();
      selectRun(res.data);
      setActiveTab('overview');
    } catch (err) {
      setError(err.response?.data?.detail || 'Evaluation run execution failed.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleCompareAllStrategies = async () => {
    if (!selectedDatasetId) return;
    try {
      setIsComparing(true);
      setError(null);
      const res = await evaluationApi.compareStrategies({
        dataset_id: selectedDatasetId,
        top_k: Number(topK),
        candidate_top_k: 20,
      });
      setComparisonData(res.data);
      await loadRuns();
      setActiveTab('comparison');
    } catch (err) {
      setError(err.response?.data?.detail || 'Strategy comparison benchmark failed.');
    } finally {
      setIsComparing(false);
    }
  };

  const formatScore = (val) => {
    if (val === null || val === undefined) return 'N/A';
    return (val * 100).toFixed(1) + '%';
  };

  const getScoreColor = (val) => {
    if (val === null || val === undefined) return 'text-slate-400';
    if (val >= 0.8) return 'text-emerald-600';
    if (val >= 0.6) return 'text-amber-600';
    return 'text-rose-600';
  };

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-5 border-b border-slate-200">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wider bg-indigo-50 text-indigo-700 border border-indigo-200 rounded-full">
              Enterprise Benchmark
            </span>
            <span className="px-2.5 py-0.5 text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200 rounded-full flex items-center gap-1">
              <CheckCircle2 className="w-3 h-3" /> Observability Active
            </span>
          </div>
          <h1 className="text-2xl font-bold text-slate-900">RAG Evaluation & Observability</h1>
          <p className="text-sm text-slate-500 mt-1">
            Quantify retrieval and generation quality using Ragas metrics: Faithfulness, Answer Relevancy, Context Precision, Context Recall, and Answer Correctness.
          </p>
        </div>

        {/* Global Dataset Action Buttons */}
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={handleCreateSyntheticDataset}
            disabled={isLoading}
            className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-medium text-indigo-700 bg-indigo-50 hover:bg-indigo-100 border border-indigo-200 rounded-md transition"
          >
            <Sparkles className="w-3.5 h-3.5 text-indigo-600" />
            Synthetic Benchmark
          </button>
          <button
            onClick={() => setShowNewDatasetModal(true)}
            className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-medium text-slate-700 bg-white hover:bg-slate-50 border border-slate-300 rounded-md shadow-sm transition"
          >
            <Plus className="w-3.5 h-3.5" />
            New Dataset
          </button>
        </div>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="p-4 bg-rose-50 border border-rose-200 rounded-lg flex items-start gap-3 text-rose-800">
          <AlertCircle className="w-5 h-5 shrink-0 mt-0.5 text-rose-600" />
          <div className="text-sm">
            <span className="font-semibold">Evaluation Error: </span>
            {error}
          </div>
        </div>
      )}

      {/* Control Bar: Dataset Selection & Run Launcher */}
      <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          {/* Dataset Selector */}
          <div>
            <label className="block text-xs font-semibold text-slate-600 uppercase mb-1.5">
              Evaluation Dataset
            </label>
            <select
              value={selectedDatasetId}
              onChange={(e) => setSelectedDatasetId(e.target.value)}
              className="w-full text-sm border-slate-300 rounded-lg focus:ring-indigo-500 focus:border-indigo-500"
            >
              {datasets.length === 0 ? (
                <option value="">No datasets available</option>
              ) : (
                datasets.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name} ({d.sample_count} samples) v{d.version}
                  </option>
                ))
              )}
            </select>
          </div>

          {/* Strategy Selector */}
          <div>
            <label className="block text-xs font-semibold text-slate-600 uppercase mb-1.5">
              Retrieval Strategy
            </label>
            <select
              value={selectedStrategy}
              onChange={(e) => setSelectedStrategy(e.target.value)}
              className="w-full text-sm border-slate-300 rounded-lg focus:ring-indigo-500 focus:border-indigo-500"
            >
              <option value="hybrid_rerank">Hybrid Search + BGE Reranker (Recommended)</option>
              <option value="hybrid_rrf">Hybrid Search (RRF Only)</option>
              <option value="vector">Dense Vector Search Only</option>
              <option value="bm25">Lexical BM25 Search Only</option>
            </select>
          </div>

          {/* Top-K Selector */}
          <div>
            <label className="block text-xs font-semibold text-slate-600 uppercase mb-1.5">
              Passages (Top-K)
            </label>
            <input
              type="number"
              min="1"
              max="20"
              value={topK}
              onChange={(e) => setTopK(e.target.value)}
              className="w-full text-sm border-slate-300 rounded-lg focus:ring-indigo-500 focus:border-indigo-500"
            />
          </div>

          {/* Execution Buttons */}
          <div className="flex items-end gap-2">
            <button
              onClick={handleRunEvaluation}
              disabled={isLoading || !selectedDatasetId || samples.length === 0}
              className="flex-1 inline-flex items-center justify-center gap-1.5 px-4 py-2.5 text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-300 rounded-lg shadow-sm transition"
            >
              {isLoading ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  Evaluating...
                </>
              ) : (
                <>
                  <Play className="w-4 h-4 fill-white" />
                  Evaluate Run
                </>
              )}
            </button>
            <button
              onClick={handleCompareAllStrategies}
              disabled={isComparing || !selectedDatasetId || samples.length === 0}
              title="Compare all 4 retrieval strategies side-by-side"
              className="inline-flex items-center justify-center gap-1 px-3 py-2.5 text-sm font-medium text-slate-700 bg-slate-100 hover:bg-slate-200 border border-slate-300 rounded-lg transition"
            >
              {isComparing ? (
                <RefreshCw className="w-4 h-4 animate-spin text-slate-600" />
              ) : (
                <BarChart3 className="w-4 h-4 text-slate-600" />
              )}
              Compare
            </button>
          </div>
        </div>

        {samples.length === 0 && selectedDatasetId && (
          <p className="text-xs text-amber-600 bg-amber-50 border border-amber-200 rounded p-2 flex items-center gap-1.5">
            <AlertCircle className="w-3.5 h-3.5 shrink-0" />
            This dataset contains no questions. Click "Synthetic Benchmark" above or add sample questions below before executing an evaluation run.
          </p>
        )}
      </div>

      {/* Navigation Tabs */}
      <div className="border-b border-slate-200 flex gap-6 text-sm font-medium">
        <button
          onClick={() => setActiveTab('overview')}
          className={`pb-3 border-b-2 transition ${
            activeTab === 'overview'
              ? 'border-indigo-600 text-indigo-600'
              : 'border-transparent text-slate-500 hover:text-slate-800'
          }`}
        >
          Run Results & Metrics
        </button>
        <button
          onClick={() => setActiveTab('comparison')}
          className={`pb-3 border-b-2 transition ${
            activeTab === 'comparison'
              ? 'border-indigo-600 text-indigo-600'
              : 'border-transparent text-slate-500 hover:text-slate-800'
          }`}
        >
          Strategy Comparison Matrix
        </button>
        <button
          onClick={() => setActiveTab('samples')}
          className={`pb-3 border-b-2 transition ${
            activeTab === 'samples'
              ? 'border-indigo-600 text-indigo-600'
              : 'border-transparent text-slate-500 hover:text-slate-800'
          }`}
        >
          Dataset Samples ({samples.length})
        </button>
        <button
          onClick={() => setActiveTab('history')}
          className={`pb-3 border-b-2 transition ${
            activeTab === 'history'
              ? 'border-indigo-600 text-indigo-600'
              : 'border-transparent text-slate-500 hover:text-slate-800'
          }`}
        >
          Run History ({runs.length})
        </button>
      </div>

      {/* Tab Content: OVERVIEW (Active Run) */}
      {activeTab === 'overview' && (
        <div className="space-y-6">
          {activeRun ? (
            <>
              {/* Active Run Header */}
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-slate-50 p-4 rounded-lg border border-slate-200">
                <div>
                  <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
                    Active Evaluation Run
                  </span>
                  <div className="flex items-center gap-2 mt-0.5">
                    <h3 className="text-base font-bold text-slate-900 capitalize">
                      {activeRun.retrieval_strategy.replace('_', ' ')} Strategy
                    </h3>
                    <span className="px-2 py-0.5 text-xs font-medium bg-indigo-100 text-indigo-800 rounded">
                      {activeRun.total_samples} Samples
                    </span>
                    <span
                      className={`px-2 py-0.5 text-xs font-medium rounded ${
                        activeRun.evaluation_status === 'COMPLETED'
                          ? 'bg-emerald-100 text-emerald-800'
                          : 'bg-amber-100 text-amber-800'
                      }`}
                    >
                      {activeRun.evaluation_status}
                    </span>
                  </div>
                </div>
                <div className="text-xs text-slate-500 sm:text-right">
                  <div className="flex items-center gap-1.5 justify-end">
                    <span>Engine:</span>
                    <span className={`font-semibold px-2 py-0.5 rounded text-xs ${
                      activeRun.configuration?.evaluator_type === 'ragas'
                        ? 'bg-purple-100 text-purple-800'
                        : 'bg-amber-100 text-amber-800 border border-amber-300'
                    }`}>
                      {activeRun.configuration?.evaluator_type === 'ragas'
                        ? 'Ragas (LLM-as-Judge)'
                        : 'Deterministic Offline Engine'}
                    </span>
                  </div>
                  <div className="mt-1">Duration: <span className="font-semibold text-slate-700">{activeRun.aggregate_metrics?.total_run_duration_s || 0}s</span></div>
                </div>
              </div>

              {/* Informative Callout Banner for Deterministic Mode */}
              {activeRun.configuration?.evaluator_type !== 'ragas' && (
                <div className="p-3.5 bg-amber-50 border border-amber-200 rounded-lg text-xs text-amber-900 flex items-start gap-2.5">
                  <AlertCircle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
                  <div>
                    <span className="font-bold">Deterministic Evaluation Mode: </span>
                    Scores were calculated using the local offline heuristic engine (term-overlap and token-F1 calculations) because live LLM evaluator credentials were not configured. These results are deterministic baseline metrics, not live LLM-as-judge benchmarks.
                  </div>
                </div>
              )}

              {/* Ragas Metric Scorecards */}
              <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
                <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm">
                  <div className="text-xs font-medium text-slate-500 uppercase">Faithfulness</div>
                  <div className={`text-2xl font-bold mt-1 ${getScoreColor(activeRun.aggregate_metrics?.faithfulness)}`}>
                    {formatScore(activeRun.aggregate_metrics?.faithfulness)}
                  </div>
                  <p className="text-[11px] text-slate-500 mt-1">Groundedness in context (anti-hallucination)</p>
                </div>

                <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm">
                  <div className="text-xs font-medium text-slate-500 uppercase">Answer Relevancy</div>
                  <div className={`text-2xl font-bold mt-1 ${getScoreColor(activeRun.aggregate_metrics?.answer_relevancy)}`}>
                    {formatScore(activeRun.aggregate_metrics?.answer_relevancy)}
                  </div>
                  <p className="text-[11px] text-slate-500 mt-1">Direct alignment to user inquiry</p>
                </div>

                <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm">
                  <div className="text-xs font-medium text-slate-500 uppercase">Context Precision</div>
                  <div className={`text-2xl font-bold mt-1 ${getScoreColor(activeRun.aggregate_metrics?.context_precision)}`}>
                    {formatScore(activeRun.aggregate_metrics?.context_precision)}
                  </div>
                  <p className="text-[11px] text-slate-500 mt-1">Top-ranked chunk signal-to-noise ratio</p>
                </div>

                <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm">
                  <div className="text-xs font-medium text-slate-500 uppercase">Context Recall</div>
                  <div className={`text-2xl font-bold mt-1 ${getScoreColor(activeRun.aggregate_metrics?.context_recall)}`}>
                    {formatScore(activeRun.aggregate_metrics?.context_recall)}
                  </div>
                  <p className="text-[11px] text-slate-500 mt-1">Coverage of reference facts retrieved</p>
                </div>

                <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm">
                  <div className="text-xs font-medium text-slate-500 uppercase">Answer Correctness</div>
                  <div className={`text-2xl font-bold mt-1 ${getScoreColor(activeRun.aggregate_metrics?.answer_correctness)}`}>
                    {formatScore(activeRun.aggregate_metrics?.answer_correctness)}
                  </div>
                  <p className="text-[11px] text-slate-500 mt-1">Factual agreement with ground truth</p>
                </div>
              </div>

              {/* Sample-Level Detailed Drilldown */}
              <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
                <div className="px-5 py-4 border-b border-slate-200 flex items-center justify-between">
                  <h3 className="text-sm font-bold text-slate-900">Per-Sample Metric Breakdown</h3>
                  <span className="text-xs text-slate-500">{runResults.length} Evaluated Samples</span>
                </div>

                {runResults.length === 0 ? (
                  <div className="p-8 text-center text-slate-400 text-sm">
                    No sample results available for this run.
                  </div>
                ) : (
                  <div className="divide-y divide-slate-200">
                    {runResults.map((result, idx) => {
                      const isExpanded = expandedSampleId === result.id;
                      return (
                        <div key={result.id} className="p-4 transition hover:bg-slate-50">
                          <div
                            onClick={() => setExpandedSampleId(isExpanded ? null : result.id)}
                            className="flex items-start justify-between cursor-pointer gap-4"
                          >
                            <div className="flex items-start gap-2.5">
                              <span className="px-2 py-0.5 text-xs font-mono font-semibold bg-slate-100 text-slate-700 rounded mt-0.5">
                                #{idx + 1}
                              </span>
                              <div>
                                <h4 className="text-sm font-semibold text-slate-900">
                                  {result.generated_answer ? result.generated_answer.slice(0, 100) + '...' : 'No answer generated'}
                                </h4>
                                <div className="flex items-center gap-3 text-xs text-slate-500 mt-1">
                                  <span>Latency: {result.latency_ms}ms</span>
                                  <span>Chunks: {result.retrieved_contexts?.length || 0}</span>
                                </div>
                              </div>
                            </div>

                            {/* Mini score badges */}
                            <div className="flex items-center gap-2">
                              <span className="text-xs font-mono text-slate-600 bg-slate-100 px-2 py-0.5 rounded">
                                Faith: {formatScore(result.faithfulness)}
                              </span>
                              <span className="text-xs font-mono text-slate-600 bg-slate-100 px-2 py-0.5 rounded">
                                Relev: {formatScore(result.answer_relevancy)}
                              </span>
                              {isExpanded ? (
                                <ChevronDown className="w-4 h-4 text-slate-400" />
                              ) : (
                                <ChevronRight className="w-4 h-4 text-slate-400" />
                              )}
                            </div>
                          </div>

                          {/* Expanded Details */}
                          {isExpanded && (
                            <div className="mt-4 pt-4 border-t border-slate-100 space-y-3 text-xs">
                              {/* Sample Metric Scores */}
                              <div>
                                <span className="font-semibold text-slate-700 uppercase tracking-wide block mb-1">
                                  Sample Metric Scores:
                                </span>
                                <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 text-xs font-mono">
                                  <div className="p-2 bg-slate-50 rounded border border-slate-200">
                                    <div className="text-[10px] text-slate-500 uppercase font-sans">Faithfulness</div>
                                    <div className={`font-bold mt-0.5 ${getScoreColor(result.faithfulness)}`}>
                                      {formatScore(result.faithfulness)}
                                    </div>
                                  </div>
                                  <div className="p-2 bg-slate-50 rounded border border-slate-200">
                                    <div className="text-[10px] text-slate-500 uppercase font-sans">Relevancy</div>
                                    <div className={`font-bold mt-0.5 ${getScoreColor(result.answer_relevancy)}`}>
                                      {formatScore(result.answer_relevancy)}
                                    </div>
                                  </div>
                                  <div className="p-2 bg-slate-50 rounded border border-slate-200">
                                    <div className="text-[10px] text-slate-500 uppercase font-sans">Precision</div>
                                    <div className={`font-bold mt-0.5 ${getScoreColor(result.context_precision)}`}>
                                      {result.context_precision !== null ? formatScore(result.context_precision) : 'N/A (No GT)'}
                                    </div>
                                  </div>
                                  <div className="p-2 bg-slate-50 rounded border border-slate-200">
                                    <div className="text-[10px] text-slate-500 uppercase font-sans">Recall</div>
                                    <div className={`font-bold mt-0.5 ${getScoreColor(result.context_recall)}`}>
                                      {result.context_recall !== null ? formatScore(result.context_recall) : 'N/A (No GT)'}
                                    </div>
                                  </div>
                                  <div className="p-2 bg-slate-50 rounded border border-slate-200">
                                    <div className="text-[10px] text-slate-500 uppercase font-sans">Correctness</div>
                                    <div className={`font-bold mt-0.5 ${getScoreColor(result.answer_correctness)}`}>
                                      {result.answer_correctness !== null ? formatScore(result.answer_correctness) : 'N/A (No GT)'}
                                    </div>
                                  </div>
                                </div>
                              </div>

                              <div>
                                <span className="font-semibold text-slate-700 uppercase tracking-wide block mb-1">
                                  Generated RAG Answer:
                                </span>
                                <div className="p-3 bg-slate-50 rounded-lg text-slate-800 leading-relaxed font-sans border border-slate-200">
                                  {result.generated_answer}
                                </div>
                              </div>

                              <div>
                                <span className="font-semibold text-slate-700 uppercase tracking-wide block mb-1">
                                  Retrieved Context Passages ({result.retrieved_contexts?.length || 0}):
                                </span>
                                <div className="space-y-2">
                                  {result.retrieved_contexts?.map((ctx, cIdx) => (
                                    <div key={cIdx} className="p-2.5 bg-indigo-50/50 rounded border border-indigo-100 text-slate-700 font-mono text-[11px]">
                                      <span className="font-bold text-indigo-700 mr-1.5">[S{cIdx + 1}]</span>
                                      {ctx}
                                    </div>
                                  ))}
                                </div>
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="p-12 text-center bg-white border border-slate-200 rounded-xl shadow-sm">
              <Activity className="w-10 h-10 text-slate-300 mx-auto mb-3" />
              <h3 className="text-base font-semibold text-slate-700">No Evaluation Run Selected</h3>
              <p className="text-sm text-slate-500 mt-1 max-w-md mx-auto">
                Select a dataset and retrieval strategy above, then click "Evaluate Run" to measure RAG quality.
              </p>
            </div>
          )}
        </div>
      )}

      {/* Tab Content: COMPARISON MATRIX */}
      {activeTab === 'comparison' && (
        <div className="space-y-6">
          <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
            <h3 className="text-base font-bold text-slate-900 mb-2">
              Retrieval Strategy Benchmark Comparison
            </h3>
            <p className="text-sm text-slate-500 mb-6">
              Empirical side-by-side comparison of retrieval configurations over the exact same evaluation dataset.
            </p>

            {comparisonData ? (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm border-collapse">
                  <thead>
                    <tr className="border-b border-slate-200 bg-slate-50 text-xs font-semibold text-slate-600 uppercase">
                      <th className="py-3 px-4">Retrieval Strategy</th>
                      <th className="py-3 px-4">Faithfulness</th>
                      <th className="py-3 px-4">Answer Relevancy</th>
                      <th className="py-3 px-4">Context Precision</th>
                      <th className="py-3 px-4">Context Recall</th>
                      <th className="py-3 px-4">Answer Correctness</th>
                      <th className="py-3 px-4">Mean Latency</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-200">
                    {comparisonData.comparison?.map((row) => (
                      <tr key={row.run_id} className="hover:bg-slate-50">
                        <td className="py-3.5 px-4 font-semibold capitalize text-slate-800">
                          {row.retrieval_strategy.replace('_', ' ')}
                        </td>
                        <td className="py-3.5 px-4 font-mono font-bold text-emerald-600">
                          {formatScore(row.metrics?.faithfulness)}
                        </td>
                        <td className="py-3.5 px-4 font-mono font-bold text-indigo-600">
                          {formatScore(row.metrics?.answer_relevancy)}
                        </td>
                        <td className="py-3.5 px-4 font-mono font-bold text-purple-600">
                          {formatScore(row.metrics?.context_precision)}
                        </td>
                        <td className="py-3.5 px-4 font-mono font-bold text-cyan-600">
                          {formatScore(row.metrics?.context_recall)}
                        </td>
                        <td className="py-3.5 px-4 font-mono font-bold text-emerald-700">
                          {formatScore(row.metrics?.answer_correctness)}
                        </td>
                        <td className="py-3.5 px-4 font-mono text-slate-600">
                          {row.metrics?.mean_latency_ms || 0} ms
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="text-center py-10">
                <p className="text-sm text-slate-500 mb-4">
                  No multi-strategy comparison run loaded yet.
                </p>
                <button
                  onClick={handleCompareAllStrategies}
                  disabled={isComparing || samples.length === 0}
                  className="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-300 rounded-lg shadow-sm transition"
                >
                  <BarChart3 className="w-4 h-4" />
                  Run All 4 Strategies Comparison
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Tab Content: SAMPLES */}
      {activeTab === 'samples' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-base font-bold text-slate-900">
              Dataset Questions & Reference Ground Truth
            </h3>
            <button
              onClick={() => setShowAddSampleModal(true)}
              className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-medium text-white bg-indigo-600 hover:bg-indigo-700 rounded shadow-sm transition"
            >
              <Plus className="w-3.5 h-3.5" />
              Add Question
            </button>
          </div>

          <div className="bg-white border border-slate-200 rounded-xl shadow-sm divide-y divide-slate-200">
            {samples.length === 0 ? (
              <div className="p-8 text-center text-slate-400 text-sm">
                No samples in this dataset. Click "Add Question" or "Synthetic Benchmark" above.
              </div>
            ) : (
              samples.map((s, idx) => (
                <div key={s.id} className="p-4 space-y-2">
                  <div className="flex items-start justify-between">
                    <span className="text-xs font-mono font-semibold bg-slate-100 text-slate-700 px-2 py-0.5 rounded">
                      Sample #{idx + 1}
                    </span>
                    <span className="text-[11px] text-slate-400">
                      {new Date(s.created_at).toLocaleDateString()}
                    </span>
                  </div>
                  <h4 className="text-sm font-semibold text-slate-900">{s.question}</h4>
                  {s.ground_truth && (
                    <div className="text-xs text-slate-600 bg-slate-50 p-2.5 rounded border border-slate-100">
                      <span className="font-semibold text-emerald-700 uppercase tracking-wide mr-1.5">
                        Ground Truth:
                      </span>
                      {s.ground_truth}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {/* Tab Content: HISTORY */}
      {activeTab === 'history' && (
        <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
          <table className="w-full text-left text-sm border-collapse">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-xs font-semibold text-slate-600 uppercase">
                <th className="py-3 px-4">Date</th>
                <th className="py-3 px-4">Strategy</th>
                <th className="py-3 px-4">Engine</th>
                <th className="py-3 px-4">Status</th>
                <th className="py-3 px-4">Samples</th>
                <th className="py-3 px-4">Faithfulness</th>
                <th className="py-3 px-4">Relevancy</th>
                <th className="py-3 px-4">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {runs.map((r) => (
                <tr key={r.id} className="hover:bg-slate-50">
                  <td className="py-3 px-4 text-xs text-slate-500">
                    {new Date(r.created_at).toLocaleString()}
                  </td>
                  <td className="py-3 px-4 font-semibold capitalize text-slate-800">
                    {r.retrieval_strategy.replace('_', ' ')}
                  </td>
                  <td className="py-3 px-4 text-xs">
                    <span className={`px-2 py-0.5 rounded font-mono font-medium ${
                      r.configuration?.evaluator_type === 'ragas'
                        ? 'bg-purple-100 text-purple-800'
                        : 'bg-amber-100 text-amber-800'
                    }`}>
                      {r.configuration?.evaluator_type === 'ragas' ? 'Ragas' : 'Deterministic'}
                    </span>
                  </td>
                  <td className="py-3 px-4">
                    <span
                      className={`px-2 py-0.5 text-xs font-medium rounded ${
                        r.evaluation_status === 'COMPLETED'
                          ? 'bg-emerald-100 text-emerald-800'
                          : 'bg-amber-100 text-amber-800'
                      }`}
                    >
                      {r.evaluation_status}
                    </span>
                  </td>
                  <td className="py-3 px-4 font-mono">{r.completed_samples}/{r.total_samples}</td>
                  <td className="py-3 px-4 font-mono text-emerald-600 font-bold">
                    {formatScore(r.aggregate_metrics?.faithfulness)}
                  </td>
                  <td className="py-3 px-4 font-mono text-indigo-600 font-bold">
                    {formatScore(r.aggregate_metrics?.answer_relevancy)}
                  </td>
                  <td className="py-3 px-4">
                    <button
                      onClick={() => {
                        selectRun(r);
                        setActiveTab('overview');
                      }}
                      className="text-xs font-medium text-indigo-600 hover:text-indigo-800"
                    >
                      View Details
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Modal: New Dataset */}
      {showNewDatasetModal && (
        <div className="fixed inset-0 bg-slate-900/50 flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-xl max-w-md w-full p-6 shadow-xl space-y-4">
            <h3 className="text-base font-bold text-slate-900">Create Evaluation Dataset</h3>
            <form onSubmit={handleCreateDataset} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-600 uppercase mb-1">
                  Dataset Name
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Q4 Financial Benchmark"
                  value={newDatasetName}
                  onChange={(e) => setNewDatasetName(e.target.value)}
                  className="w-full text-sm border-slate-300 rounded-lg focus:ring-indigo-500 focus:border-indigo-500"
                />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowNewDatasetModal(false)}
                  className="px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-100 rounded"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isLoading}
                  className="px-4 py-1.5 text-xs font-medium text-white bg-indigo-600 hover:bg-indigo-700 rounded shadow-sm"
                >
                  Create Dataset
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Add Sample */}
      {showAddSampleModal && (
        <div className="fixed inset-0 bg-slate-900/50 flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-xl max-w-lg w-full p-6 shadow-xl space-y-4">
            <h3 className="text-base font-bold text-slate-900">Add Evaluation Sample</h3>
            <form onSubmit={handleAddSample} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-600 uppercase mb-1">
                  Question *
                </label>
                <textarea
                  required
                  rows={3}
                  placeholder="Enter evaluation prompt or question..."
                  value={newQuestion}
                  onChange={(e) => setNewQuestion(e.target.value)}
                  className="w-full text-sm border-slate-300 rounded-lg focus:ring-indigo-500 focus:border-indigo-500"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-slate-600 uppercase mb-1">
                  Reference Ground Truth (Optional)
                </label>
                <textarea
                  rows={3}
                  placeholder="Human-verified reference answer for Context Recall and Answer Correctness calculation..."
                  value={newGroundTruth}
                  onChange={(e) => setNewGroundTruth(e.target.value)}
                  className="w-full text-sm border-slate-300 rounded-lg focus:ring-indigo-500 focus:border-indigo-500"
                />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowAddSampleModal(false)}
                  className="px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-100 rounded"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isLoading}
                  className="px-4 py-1.5 text-xs font-medium text-white bg-indigo-600 hover:bg-indigo-700 rounded shadow-sm"
                >
                  Save Sample
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
