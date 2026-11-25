import { useRef } from 'react';
import { ChatIcon, CloseIcon, EditIcon, FileIcon, MoonIcon, PaperclipIcon, SunIcon, TrashIcon } from './Icons';

export default function Sidebar({
  open, onClose, chats, activeChatId, onNewChat, onOpenChat, onRemoveChat,
  documents, activeDocId, onSelectDoc, onDeleteDoc, onUpload, uploading, uploadError, theme, onToggleTheme,
}) {
  const fileRef = useRef(null);

  return (
    <>
      <div className={`backdrop ${open ? 'show' : ''}`} onClick={onClose} />
      <aside className={`sidebar ${open ? 'open' : ''}`} aria-label="Sidebar">
        <div className="sidebar-top">
          <button type="button" className="new-chat" onClick={onNewChat}><EditIcon size={18} /> New chat</button>
          <button type="button" className="icon-btn sidebar-close" onClick={onClose} aria-label="Close sidebar"><CloseIcon size={18} /></button>
        </div>

        <div className="sidebar-scroll">
          <section>
            <div className="section-head">
              <h3>Documents</h3>
              <button type="button" className="icon-btn" onClick={() => fileRef.current?.click()} disabled={uploading} aria-label="Upload a document" title="Upload PDF / TXT">
                <PaperclipIcon size={16} />
              </button>
              <input ref={fileRef} type="file" hidden accept=".pdf,.txt,application/pdf,text/plain" onChange={(e) => { onUpload(e.target.files[0]); e.target.value = ''; }} />
            </div>
            {uploading && <div className="side-note">Uploading and indexing…</div>}
            {uploadError && <div className="side-note error">{uploadError}</div>}
            <ul className="side-list">
              {documents.map((doc) => (
                <li key={doc.id} className={doc.id === activeDocId ? 'active' : ''}>
                  <button type="button" className="side-item" onClick={() => onSelectDoc(doc.id)} title={doc.name}>
                    <FileIcon size={16} /><span>{doc.name}</span>
                  </button>
                  <button type="button" className="icon-btn hover-only" onClick={() => onDeleteDoc(doc.id)} aria-label={`Delete ${doc.name}`}><TrashIcon size={15} /></button>
                </li>
              ))}
              {documents.length === 0 && !uploading && (
                <li><button type="button" className="side-empty" onClick={() => fileRef.current?.click()}>Upload your resume (PDF or TXT) to ask about it</button></li>
              )}
            </ul>
          </section>

          <section>
            <div className="section-head"><h3>Recent</h3></div>
            <ul className="side-list">
              {chats.map((chat) => (
                <li key={chat.id} className={chat.id === activeChatId ? 'active' : ''}>
                  <button type="button" className="side-item" onClick={() => onOpenChat(chat.id)} title={chat.title}>
                    <ChatIcon size={16} /><span>{chat.title}</span>
                  </button>
                  <button type="button" className="icon-btn hover-only" onClick={() => onRemoveChat(chat.id)} aria-label="Remove from history"><TrashIcon size={15} /></button>
                </li>
              ))}
              {chats.length === 0 && <li className="side-empty static">Your conversations will appear here</li>}
            </ul>
          </section>
        </div>

        <div className="sidebar-bottom">
          <button type="button" className="side-item" onClick={onToggleTheme}>
            {theme === 'dark' ? <SunIcon size={16} /> : <MoonIcon size={16} />}<span>{theme === 'dark' ? 'Light mode' : 'Dark mode'}</span>
          </button>
        </div>
      </aside>
    </>
  );
}
