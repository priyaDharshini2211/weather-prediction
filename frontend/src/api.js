const BASE = import.meta.env.VITE_API_URL || '/api';

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(`${BASE}${path}`, options);
  } catch {
    throw new Error('Cannot reach the server. Is the backend running?');
  }
  if (response.status === 204) return null;
  let body = null;
  try {
    body = await response.json();
  } catch {
    /* non-JSON error body */
  }
  if (!response.ok) throw new Error(body?.error || `Request failed (HTTP ${response.status})`);
  return body;
}

export const api = {
  listDocuments: () => request('/documents/'),
  uploadDocument: (file) => {
    const form = new FormData();
    form.append('file', file);
    return request('/documents/', { method: 'POST', body: form });
  },
  deleteDocument: (id) => request(`/documents/${id}/`, { method: 'DELETE' }),
  messages: (conversationId) => request(`/conversations/${conversationId}/messages/`),
  chat: (payload) =>
    request('/chat/', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }),
};
