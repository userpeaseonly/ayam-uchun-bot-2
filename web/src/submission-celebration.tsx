import type { CSSProperties } from 'react';
import './submission-celebration.css';

// Fixed positions keep result polling from moving the burst.
const pieces = Array.from({ length: 44 }, (_, index) => ({
  '--confetti-x': `${3 + (index * 37 % 94)}%`,
  '--confetti-drift': `${(index * 53 % 170) - 85}px`,
  '--confetti-delay': `${index % 8 * 55}ms`,
  '--confetti-duration': `${2100 + index % 5 * 160}ms`,
  '--confetti-turn': `${(index % 2 ? 1 : -1) * (260 + index * 19)}deg`,
  '--confetti-color': ['#571b40', '#e59abc', '#d6a34e', '#64836b', '#f4c7dc'][index % 5],
}) as CSSProperties);

export function SubmissionCelebration() {
  return <div className="submission-celebration" aria-hidden="true">
    <div className="celebration-halo" />
    {pieces.map((style, index) => <i className="celebration-confetti" key={index} style={style} />)}
  </div>;
}
