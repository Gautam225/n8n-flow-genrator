import type React from 'react';
import type { ExamplePrompt } from '../../types';
import { EXAMPLE_PROMPTS } from '../../constants/examplePrompts';
import { Clock, Webhook, RefreshCw, ShieldAlert } from 'lucide-react';

interface ExamplePromptsProps {
  onSelectPrompt: (promptText: string) => void;
}

export const ExamplePrompts: React.FC<ExamplePromptsProps> = ({ onSelectPrompt }) => {
  const getCategoryIcon = (category: ExamplePrompt['category']) => {
    switch (category) {
      case 'Scheduling':
        return <Clock size={13} />;
      case 'Webhooks':
        return <Webhook size={13} />;
      case 'Data Sync':
        return <RefreshCw size={13} />;
      case 'Fault Tolerance':
        return <ShieldAlert size={13} />;
    }
  };

  return (
    <div className="examples-section">
      <div className="section-label">Example automation scenarios</div>
      <div className="examples-grid">
        {EXAMPLE_PROMPTS.map((ex) => (
          <button
            key={ex.id}
            type="button"
            className="example-card"
            onClick={() => onSelectPrompt(ex.prompt)}
            title="Click to populate the prompt input"
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                color: 'var(--brand-primary)',
              }}
            >
              {getCategoryIcon(ex.category)}
              <span className="example-category">{ex.category}</span>
            </div>
            <div className="example-title">{ex.title}</div>
            <div className="example-snippet">{ex.description}</div>
          </button>
        ))}
      </div>
    </div>
  );
};
