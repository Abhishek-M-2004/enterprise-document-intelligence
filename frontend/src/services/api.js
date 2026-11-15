/**
 * Axios API client configured with interceptors, token injection, and anti-race refresh logic.
 */
import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 10000,
  withCredentials: true, // Send HttpOnly session cookies
  headers: {
    'Content-Type': 'application/json',
    Accept: 'application/json',
  },
});

let currentAccessToken = null;
let currentTenantId = null;
let getAccessToken = () => currentAccessToken;
let getActiveTenantId = () => currentTenantId;
let onTokenRefreshed = () => { };
let onAuthFailed = () => { };

export const setApiAccessToken = (token) => {
  currentAccessToken = token;
};

export const configureApiAuth = (callbacks) => {
  if (callbacks.getAccessToken) getAccessToken = callbacks.getAccessToken;
  if (callbacks.getActiveTenantId) getActiveTenantId = callbacks.getActiveTenantId;
  if (callbacks.onTokenRefreshed) onTokenRefreshed = callbacks.onTokenRefreshed;
  if (callbacks.onAuthFailed) onAuthFailed = callbacks.onAuthFailed;
};

// Request interceptor: attach bearer token and active tenant header
apiClient.interceptors.request.use(
  (config) => {
    // If request already has an explicitly set Authorization header (e.g. from retry), preserve it
    const existingAuth = config.headers['Authorization'] || (config.headers?.get && config.headers.get('Authorization'));
    if (!existingAuth) {
      const token = currentAccessToken || getAccessToken() || sessionStorage.getItem('access_token');
      if (token) {
        if (config.headers?.set) {
          config.headers.set('Authorization', `Bearer ${token}`);
        } else {
          config.headers['Authorization'] = `Bearer ${token}`;
        }
      }
    }
    const tenantId = currentTenantId || getActiveTenantId() || sessionStorage.getItem('active_tenant_id');
    const existingTenant = config.headers['X-Tenant-ID'] || (config.headers?.get && config.headers.get('X-Tenant-ID'));
    if (tenantId && !existingTenant) {
      if (config.headers?.set) {
        config.headers.set('X-Tenant-ID', tenantId);
      } else {
        config.headers['X-Tenant-ID'] = tenantId;
      }
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Concurrency lock for refresh token rotation to prevent race conditions
let isRefreshing = false;
let failedQueue = [];

const processQueue = (error, token = null) => {
  failedQueue.forEach((prom) => {
    if (error) {
      prom.reject(error);
    } else {
      prom.resolve(token);
    }
  });
  failedQueue = [];
};

// Response interceptor: handle token expiration and automatic single-flight refresh
apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;

    // Do not attempt refresh on auth endpoints to avoid recursion loops
    if (
      !error.response ||
      error.response.status !== 401 ||
      originalRequest._retry ||
      originalRequest.url.includes('/api/v1/auth/login') ||
      originalRequest.url.includes('/api/v1/auth/register') ||
      originalRequest.url.includes('/api/v1/auth/refresh')
    ) {
      return Promise.reject(error);
    }

    if (isRefreshing) {
      return new Promise((resolve, reject) => {
        failedQueue.push({ resolve, reject });
      })
        .then((token) => {
          if (originalRequest.headers?.set) {
            originalRequest.headers.set('Authorization', `Bearer ${token}`);
          } else {
            originalRequest.headers['Authorization'] = `Bearer ${token}`;
          }
          return apiClient(originalRequest);
        })
        .catch((err) => Promise.reject(err));
    }

    originalRequest._retry = true;
    isRefreshing = true;

    try {
      const res = await axios.post(
        `${API_BASE_URL}/api/v1/auth/refresh`,
        {},
        { withCredentials: true }
      );
      const newAccessToken = res.data.access_token;
      currentAccessToken = newAccessToken;
      sessionStorage.setItem('access_token', newAccessToken);
      onTokenRefreshed(newAccessToken);
      processQueue(null, newAccessToken);
      if (originalRequest.headers?.set) {
        originalRequest.headers.set('Authorization', `Bearer ${newAccessToken}`);
      } else {
        originalRequest.headers['Authorization'] = `Bearer ${newAccessToken}`;
      }
      return apiClient(originalRequest);
    } catch (refreshErr) {
      currentAccessToken = null;
      processQueue(refreshErr, null);
      onAuthFailed();
      return Promise.reject(refreshErr);
    } finally {
      isRefreshing = false;
    }
  }
);

// Authentication API methods
export const authApi = {
  register: (data) => apiClient.post('/api/v1/auth/register', data),
  login: (data) => apiClient.post('/api/v1/auth/login', data),
  refresh: () => apiClient.post('/api/v1/auth/refresh', {}),
  logout: () => apiClient.post('/api/v1/auth/logout', {}),
  getMe: () => apiClient.get('/api/v1/auth/me'),
};

// Tenant & Membership API methods
export const tenantApi = {
  list: () => apiClient.get('/api/v1/tenants'),
  get: (tenantId) => apiClient.get(`/api/v1/tenants/${tenantId}`),
  update: (tenantId, data) => apiClient.patch(`/api/v1/tenants/${tenantId}`, data),
  listMembers: (tenantId) => apiClient.get(`/api/v1/tenants/${tenantId}/members`),
  addMember: (tenantId, data) => apiClient.post(`/api/v1/tenants/${tenantId}/members`, data),
  updateMemberRole: (tenantId, userId, data) =>
    apiClient.patch(`/api/v1/tenants/${tenantId}/members/${userId}`, data),
  removeMember: (tenantId, userId) =>
    apiClient.delete(`/api/v1/tenants/${tenantId}/members/${userId}`),
};

// Document Management API methods
export const documentApi = {
  upload: (file, onUploadProgress) => {
    const formData = new FormData();
    formData.append('file', file);
    return apiClient.post('/api/v1/documents/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
      onUploadProgress,
    });
  },
  list: (params = {}) => apiClient.get('/api/v1/documents', { params }),
  get: (documentId) => apiClient.get(`/api/v1/documents/${documentId}`),
  getDetail: (documentId) => apiClient.get(`/api/v1/documents/${documentId}/detail`),
  getStatus: (documentId) => apiClient.get(`/api/v1/documents/${documentId}/status`),
  getFileBlob: (documentId) =>
    apiClient.get(`/api/v1/documents/${documentId}/file`, { responseType: 'blob' }),
  delete: (documentId) => apiClient.delete(`/api/v1/documents/${documentId}`),
};

// Search & Retrieval API methods (Phase 4 & Phase 5)
export const searchApi = {
  vector: (data) => apiClient.post('/api/v1/search/vector', data),
  bm25: (data) => apiClient.post('/api/v1/search/bm25', data),
  hybrid: (data) => apiClient.post('/api/v1/search/hybrid', data),
  rerank: (data) => apiClient.post('/api/v1/search/rerank', data),
};

// RAG Chat & Conversational API methods (Phase 6)
export const chatApi = {
  createSession: (data = {}) => apiClient.post('/api/v1/chat/sessions', data),
  listSessions: () => apiClient.get('/api/v1/chat/sessions'),
  getSession: (sessionId) => apiClient.get(`/api/v1/chat/sessions/${sessionId}`),
  deleteSession: (sessionId) => apiClient.delete(`/api/v1/chat/sessions/${sessionId}`),
  sendMessage: (sessionId, data) => apiClient.post(`/api/v1/chat/sessions/${sessionId}/messages`, data),
  askStateless: (data) => apiClient.post('/api/v1/chat/ask', data),
  getStreamUrl: (sessionId) => `${API_BASE_URL}/api/v1/chat/sessions/${sessionId}/messages/stream`,
};

// Evaluation & Observability API methods (Phase 7)
export const evaluationApi = {
  createDataset: (data) => apiClient.post('/api/v1/evaluation/datasets', data),
  createSyntheticDataset: (params = {}) => apiClient.post('/api/v1/evaluation/datasets/synthetic', null, { params }),
  listDatasets: () => apiClient.get('/api/v1/evaluation/datasets'),
  getDataset: (datasetId) => apiClient.get(`/api/v1/evaluation/datasets/${datasetId}`),
  addSample: (datasetId, data) => apiClient.post(`/api/v1/evaluation/datasets/${datasetId}/samples`, data),
  listSamples: (datasetId) => apiClient.get(`/api/v1/evaluation/datasets/${datasetId}/samples`),
  updateSample: (datasetId, sampleId, data) => apiClient.put(`/api/v1/evaluation/datasets/${datasetId}/samples/${sampleId}`, data),
  importSamples: (datasetId, file) => {
    const formData = new FormData();
    formData.append('file', file);
    return apiClient.post(`/api/v1/evaluation/datasets/${datasetId}/import`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  createRun: (data) => apiClient.post('/api/v1/evaluation/runs', data),
  listRuns: (params = {}) => apiClient.get('/api/v1/evaluation/runs', { params }),
  getRun: (runId) => apiClient.get(`/api/v1/evaluation/runs/${runId}`),
  getRunResults: (runId) => apiClient.get(`/api/v1/evaluation/runs/${runId}/results`),
  compareStrategies: (params) => apiClient.get('/api/v1/evaluation/compare', { params }),
};

// Health diagnostic API
export const getSystemHealth = async () => {
  const response = await apiClient.get('/api/v1/health');
  return response.data;
};

export default apiClient;
