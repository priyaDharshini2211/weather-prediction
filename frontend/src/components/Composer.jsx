import { useEffect, useRef } from 'react';
import { ArrowUpIcon, FileIcon, PaperclipIcon, SpinnerIcon } from './Icons';

export default function Composer({ value, onChange, onSend, sending, activeDoc, onUpload, uploading }) {
  const textRef = useRef(null);
  const fileRef = useRef(null);

  useEffect(() => {
    const el = textRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [value]);

  const submit = () => { if (value.trim() && !sending) onSend(value); };

  return (
    <div className="composer-wrap">
      <form className="composer" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        {activeDoc && <div className="doc-chip" title="Document questions will use this file"><FileIcon size={14} /><span>{activeDoc.name}</span></div>}
        <textarea
          ref={textRef}
          rows={1}
          value={value}
          maxLength={2000}
          placeholder="Ask about the weather or your document…"
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit(); }
          }}
        />
        <div className="composer-actions">
          <button type="button" className="icon-btn round" onClick={() => fileRef.current?.click()} disabled={uploading} aria-label="Attach a PDF or TXT" title="Attach a PDF or TXT">
            {uploading ? <SpinnerIcon size={18} className="spin" /> : <PaperclipIcon size={18} />}
          </button>
          <input ref={fileRef} type="file" hidden accept=".pdf,.txt,application/pdf,text/plain" onChange={(e) => { onUpload(e.target.files[0]); e.target.value = ''; }} />
          <button type="submit" className="send" disabled={sending || !value.trim()} aria-label="Send message">
            {sending ? <SpinnerIcon size={18} className="spin" /> : <ArrowUpIcon size={18} />}
          </button>
        </div>
      </form>
      <p className="disclaimer">Answers come from live weather APIs and your uploaded document. Check important details.</p>
    </div>
  );
}
