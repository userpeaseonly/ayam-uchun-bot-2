import { Fragment } from 'react';

// Formatting markers become elements; teacher/source HTML is never executed.
export function RichText({ text }: { text: string }) {
  const tokens = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*|<u>[\s\S]*?<\/u>)/g);
  return <span className="rich-text">{tokens.map((token, i) => token.startsWith('**') ? <strong key={i}>{token.slice(2, -2)}</strong> : token.startsWith('*') ? <em key={i}>{token.slice(1, -1)}</em> : token.startsWith('<u>') ? <u key={i}>{token.slice(3, -4)}</u> : <Fragment key={i}>{token}</Fragment>)}</span>;
}
