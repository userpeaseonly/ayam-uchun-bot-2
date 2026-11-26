import { useEffect, type ReactNode } from 'react';
import './content-protection.css';

export function isSaveShortcut(key: string, ctrlKey: boolean, metaKey: boolean) {
  return (ctrlKey || metaKey) && ['p', 's'].includes(key.toLowerCase());
}

function editing(target: EventTarget | null) {
  return target instanceof Element && Boolean(target.closest('input,textarea,select,[contenteditable="true"]'));
}

/** UI deterrents only. A website cannot prevent OS screenshots or media capture. */
export function ProtectedTest({ children }: { children: ReactNode }) {
  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if (isSaveShortcut(event.key, event.ctrlKey, event.metaKey)) event.preventDefault();
    };
    window.addEventListener('keydown', shortcut);
    return () => window.removeEventListener('keydown', shortcut);
  }, []);
  return <div className="protected-test" onContextMenu={event => { if (!editing(event.target)) event.preventDefault(); }}
    onCopy={event => { if (!editing(event.target)) event.preventDefault(); }}
    onCut={event => { if (!editing(event.target)) event.preventDefault(); }} onDragStart={event => event.preventDefault()}>{children}</div>;
}
