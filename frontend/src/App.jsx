import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from './api';
import Composer from './components/Composer';
import { ChartIcon, CloudIcon, FileIcon, MenuIcon, EditIcon } from './components/Icons';
import Message, { Thinking } from './components/Message';
import Sidebar from './components/Sidebar';

const SUGGESTIONS = [
  { Icon: CloudIcon, tag: 'Weather', text: 'What is the weather in Chennai today?' },
  { Icon: ChartIcon, tag: 'Table + charts', text: 'List the last 10 days of weather in Chennai' },
  { Icon: ChartIcon, tag: 'Pie chart', text: 'Show a pie chart of weather conditions in Mumbai for the last 10 days' },
  { Icon: FileIcon, tag: 'Resume', text: 'What are the skills mentioned in my resume?' },
  { Icon: FileIcon, tag: 'Resume', text: 'Summarise my education and projects' },
  { Icon: FileIcon, tag: 'Resume + web', text: 'What is Docker? Also, do I list it as a skill?' },
];

const CHATS_KEY = 'agentic-chat.history.v1';
const THEME_KEY = 'agentic-chat.theme';

const safeGet = (key) => { try { return localStorage.getItem(key); } catch { return null; } };
const safeSet = (key, value) => { try { localStorage.setItem(key, value); } catch { /* storage unavailable */ } };

function loadChats() {
  try { return JSON.parse(safeGet(CHATS_KEY)) ?? []; } catch { return []; }
}

function initialTheme() {
  const stored = safeGet(THEME_KEY);
  if (stored === 'light' || stored === 'dark') return stored;
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

export default function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [conversationId, setConversationId] = useState(null);
  const [chats, setChats] = useState(loadChats);
  const [documents, setDocuments] = useState([]);
  const [activeDocId, setActiveDocId] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth >= 900);
  const [theme, setTheme] = useState(initialTheme);
  const scrollRef = useRef(null);
  const epoch = useRef(0); // bumped whenever the visible conversation changes, so late replies never land in the wrong thread

  useEffect(() => { document.documentElement.dataset.theme = theme; safeSet(THEME_KEY, theme); }, [theme]);
  useEffect(() => { safeSet(CHATS_KEY, JSON.stringify(chats)); }, [chats]);

  const loadDocuments = useCallback(async (preferId) => {
    for (let attempt = 0; attempt < 3; attempt += 1) {
      try {
        const docs = await api.listDocuments();
        setDocuments(docs);
        setActiveDocId((current) => preferId ?? (docs.some((d) => d.id === current) ? current : docs[0]?.id ?? null));
        return;
      } catch {
        // The server may be busy or still starting; retry quietly. Persistent failures surface when the user sends a message.
        await new Promise((resolve) => setTimeout(resolve, 1500 * (attempt + 1)));
      }
    }
  }, []);
  useEffect(() => { loadDocuments(); }, [loadDocuments]);

  const scrollToBottom = useCallback(() => {
    const el = scrollRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight });
  }, []);
  useEffect(() => { scrollToBottom(); }, [messages, sending, scrollToBottom]);

  const upload = async (file) => {
    if (!file) return;
    setUploading(true);
    setUploadError(null);
    try {
      const doc = await api.uploadDocument(file);
      await loadDocuments(doc.id);
    } catch (err) {
      setUploadError(err.message);
    } finally {
      setUploading(false);
    }
  };

  const deleteDoc = async (id) => {
    try {
      await api.deleteDocument(id);
      await loadDocuments(null);
    } catch (err) {
      setUploadError(err.message);
    }
  };

  const newChat = () => {
    epoch.current += 1;
    setSending(false);
    setMessages([]);
    setConversationId(null);
    setInput('');
    if (window.innerWidth < 900) setSidebarOpen(false);
  };

  const openChat = async (id) => {
    if (window.innerWidth < 900) setSidebarOpen(false);
    epoch.current += 1;
    setSending(false);
    try {
      const history = await api.messages(id);
      setConversationId(id);
      setMessages(history.map((m) => ({ role: m.role, content: m.content, agent: m.agent || undefined, blocks: m.blocks })));
    } catch {
      setChats((list) => list.filter((c) => c.id !== id)); // the conversation no longer exists on the server
    }
  };

  const removeChat = (id) => {
    setChats((list) => list.filter((c) => c.id !== id));
    if (id === conversationId) newChat();
  };

  const send = async (text) => {
    const question = text.trim();
    if (!question || sending) return;
    setInput('');
    setMessages((m) => [...m, { role: 'user', content: question }]);
    setSending(true);
    const mine = epoch.current;
    try {
      const reply = await api.chat({ message: question, conversation_id: conversationId, document_id: activeDocId });
      setChats((list) => (list.some((c) => c.id === reply.conversation_id) ? list : [{ id: reply.conversation_id, title: question.slice(0, 48) }, ...list]));
      if (mine !== epoch.current) return; // the user moved to another chat; the reply is still saved in history
      setConversationId(reply.conversation_id);
      setMessages((m) => [...m, { role: 'assistant', content: reply.answer, agent: reply.agent, blocks: reply.blocks, trace: reply.tool_trace, fresh: true }]);
    } catch (err) {
      if (mine === epoch.current) setMessages((m) => [...m, { role: 'assistant', content: err.message, error: true }]);
    } finally {
      if (mine === epoch.current) setSending(false);
    }
  };

  const activeDoc = documents.find((d) => d.id === activeDocId);

  return (
    <div className="app">
      <Sidebar
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        chats={chats}
        activeChatId={conversationId}
        onNewChat={newChat}
        onOpenChat={openChat}
        onRemoveChat={removeChat}
        documents={documents}
        activeDocId={activeDocId}
        onSelectDoc={setActiveDocId}
        onDeleteDoc={deleteDoc}
        onUpload={upload}
        uploading={uploading}
        uploadError={uploadError}
        theme={theme}
        onToggleTheme={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))}
      />

      <main className="main">
        <header className="topbar">
          <button type="button" className="icon-btn" onClick={() => setSidebarOpen((o) => !o)} aria-label="Toggle sidebar"><MenuIcon /></button>
          <div className="brand">Agentic Chatbot <span>Weather · Documents</span></div>
          <button type="button" className="icon-btn topbar-new" onClick={newChat} aria-label="New chat"><EditIcon /></button>
        </header>

        <div className="scroll" ref={scrollRef}>
          {messages.length === 0 && !sending ? (
            <div className="welcome">
              <h1 className="greeting">Hello there</h1>
              <p className="greeting-sub">How can I help you today?</p>
              <div className="cards">
                {SUGGESTIONS.map(({ Icon, tag, text }) => (
                  <button key={text} type="button" className="card" onClick={() => send(text)}>
                    <span>{text}</span>
                    <small><Icon size={14} />{tag}</small>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="thread">
              {messages.map((m, i) => <Message key={i} message={m} onReveal={scrollToBottom} />)}
              {sending && <Thinking />}
            </div>
          )}
        </div>

        <Composer value={input} onChange={setInput} onSend={send} sending={sending} activeDoc={activeDoc} onUpload={upload} uploading={uploading} />
      </main>
    </div>
  );
}
