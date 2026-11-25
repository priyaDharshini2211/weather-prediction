import { useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import Blocks from './Blocks';
import { CheckIcon, CloudIcon, CopyIcon, FileIcon, SparkleIcon } from './Icons';

const AGENTS = {
  weather: { label: 'Weather agent', Icon: CloudIcon },
  document: { label: 'Document agent', Icon: FileIcon },
};

export function Avatar() {
  return <div className="avatar" aria-hidden="true"><SparkleIcon size={16} /></div>;
}

const PHRASES = ['Thinking…', 'Looking that up…', 'Still working — the model is busy, thanks for waiting…'];

export function Thinking() {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(id);
  }, []);
  const phrase = seconds < 6 ? PHRASES[0] : seconds < 20 ? PHRASES[1] : PHRASES[2];
  return (
    <div className="msg assistant">
      <Avatar />
      <div className="msg-body"><div className="thinking"><span className="dots"><i /><i /><i /></span><span>{phrase}</span></div></div>
    </div>
  );
}

/** Reveals freshly received text progressively, like a streamed reply (the API itself returns the whole answer at once). */
function useReveal(text, enabled, onTick) {
  const [shown, setShown] = useState(enabled ? 0 : text.length);
  useEffect(() => {
    if (!enabled || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) { setShown(text.length); return undefined; }
    const step = Math.max(3, Math.ceil(text.length / 100));
    const id = setInterval(() => {
      setShown((n) => {
        const next = Math.min(text.length, n + step);
        if (next >= text.length) clearInterval(id);
        return next;
      });
      onTick?.();
    }, 16);
    return () => clearInterval(id);
  }, [text, enabled]); // eslint-disable-line react-hooks/exhaustive-deps
  return shown;
}

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch { /* clipboard unavailable (insecure context) */ }
  };
  return (
    <button type="button" className="icon-btn" onClick={copy} aria-label="Copy answer" title="Copy">
      {copied ? <CheckIcon size={16} /> : <CopyIcon size={16} />}
    </button>
  );
}

export default function Message({ message, onReveal }) {
  const isAssistant = message.role !== 'user';
  const shown = useReveal(message.content, isAssistant && !!message.fresh && !message.error, onReveal);

  if (!isAssistant) {
    return <div className="msg user"><div className="user-bubble">{message.content}</div></div>;
  }

  const done = shown >= message.content.length;
  const agent = AGENTS[message.agent];
  return (
    <div className="msg assistant">
      <Avatar />
      <div className="msg-body">
        {agent && <span className="agent-tag"><agent.Icon size={13} />{agent.label}</span>}
        {message.error
          ? <div className="notice notice-warning">{message.content}</div>
          : <div className="markdown"><ReactMarkdown>{message.content.slice(0, shown)}</ReactMarkdown></div>}
        {done && <Blocks blocks={message.blocks ?? []} />}
        {done && !message.error && (
          <div className="msg-actions">
            <CopyButton text={message.content} />
            {message.trace?.length > 0 && (
              <details className="trace">
                <summary>How I answered</summary>
                <pre>{JSON.stringify(message.trace, null, 2)}</pre>
              </details>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
