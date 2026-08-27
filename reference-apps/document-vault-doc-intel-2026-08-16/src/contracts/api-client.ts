// Auto-generated API client — all CRUD goes through the Data Engine
// DO NOT EDIT — regenerated from plan on each build

const API_BASE = '';

async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err?.error?.message || `Request failed: ${res.status}`);
  }
  return res.json();
}

interface ListResponse<T> { data: T[]; total: number; page: number; limit: number; }

// ─── User ───
export interface User {
  id: string;
  email: string;
  name: string;
  role: string;
  createdAt: string;
  updatedAt: string;
}
export type CreateUserInput = Omit<User, 'id' | 'createdAt' | 'updatedAt'>;
export type UpdateUserInput = Partial<CreateUserInput>;

export async function getUsers(opts?: { search?: string; [key: string]: any }): Promise<ListResponse<User>> {
  const params = new URLSearchParams();
  if (opts) Object.entries(opts).forEach(([k, v]) => { if (v) params.set(k, String(v)); });
  return apiRequest(`/api/data/users?${params}`);
}

export async function getUser(id: string): Promise<User> {
  return apiRequest(`/api/data/users/${id}`);
}

export async function createUser(data: CreateUserInput): Promise<User> {
  return apiRequest('/api/data/users', { method: 'POST', body: JSON.stringify(data) });
}

export async function updateUser(id: string, data: UpdateUserInput): Promise<User> {
  return apiRequest(`/api/data/users/${id}`, { method: 'PUT', body: JSON.stringify(data) });
}

export async function deleteUser(id: string): Promise<void> {
  await apiRequest(`/api/data/users/${id}`, { method: 'DELETE' });
}

export async function getUserStats(): Promise<{ total: number }> {
  return apiRequest('/api/data/users/stats');
}

// ─── Document ───
export interface Document {
  id: string;
  originalFilename: string;
  fileUrl: string;
  mimeType: string;
  fileSizeBytes: number;
  status: string;
  ocrText: string;
  extractedFields: any;
  confidence: number;
  pageCount: number;
  uploadedBy: string;
  processedAt: string;
  errorMessage: string;
  createdAt: string;
  updatedAt: string;
}
export type CreateDocumentInput = Omit<Document, 'id' | 'createdAt' | 'updatedAt'>;
export type UpdateDocumentInput = Partial<CreateDocumentInput>;

export async function getDocuments(opts?: { search?: string; [key: string]: any }): Promise<ListResponse<Document>> {
  const params = new URLSearchParams();
  if (opts) Object.entries(opts).forEach(([k, v]) => { if (v) params.set(k, String(v)); });
  return apiRequest(`/api/data/documents?${params}`);
}

export async function getDocument(id: string): Promise<Document> {
  return apiRequest(`/api/data/documents/${id}`);
}

export async function createDocument(data: CreateDocumentInput): Promise<Document> {
  return apiRequest('/api/data/documents', { method: 'POST', body: JSON.stringify(data) });
}

export async function updateDocument(id: string, data: UpdateDocumentInput): Promise<Document> {
  return apiRequest(`/api/data/documents/${id}`, { method: 'PUT', body: JSON.stringify(data) });
}

export async function deleteDocument(id: string): Promise<void> {
  await apiRequest(`/api/data/documents/${id}`, { method: 'DELETE' });
}

export async function getDocumentStats(): Promise<{ total: number }> {
  return apiRequest('/api/data/documents/stats');
}

// ─── ProcessDocumentJob ───
export interface ProcessDocumentJob {
  id: string;
  documentId: string;
  step: string;
  startedAt: string;
  completedAt: string;
  error: string;
  createdAt: string;
  updatedAt: string;
}
export type CreateProcessDocumentJobInput = Omit<ProcessDocumentJob, 'id' | 'createdAt' | 'updatedAt'>;
export type UpdateProcessDocumentJobInput = Partial<CreateProcessDocumentJobInput>;

export async function getProcessDocumentJobs(opts?: { search?: string; [key: string]: any }): Promise<ListResponse<ProcessDocumentJob>> {
  const params = new URLSearchParams();
  if (opts) Object.entries(opts).forEach(([k, v]) => { if (v) params.set(k, String(v)); });
  return apiRequest(`/api/data/process_document_jobs?${params}`);
}

export async function getProcessDocumentJob(id: string): Promise<ProcessDocumentJob> {
  return apiRequest(`/api/data/process_document_jobs/${id}`);
}

export async function createProcessDocumentJob(data: CreateProcessDocumentJobInput): Promise<ProcessDocumentJob> {
  return apiRequest('/api/data/process_document_jobs', { method: 'POST', body: JSON.stringify(data) });
}

export async function updateProcessDocumentJob(id: string, data: UpdateProcessDocumentJobInput): Promise<ProcessDocumentJob> {
  return apiRequest(`/api/data/process_document_jobs/${id}`, { method: 'PUT', body: JSON.stringify(data) });
}

export async function deleteProcessDocumentJob(id: string): Promise<void> {
  await apiRequest(`/api/data/process_document_jobs/${id}`, { method: 'DELETE' });
}

export async function getProcessDocumentJobStats(): Promise<{ total: number }> {
  return apiRequest('/api/data/process_document_jobs/stats');
}
