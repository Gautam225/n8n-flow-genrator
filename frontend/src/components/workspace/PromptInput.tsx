import React, { useState } from 'react';
import { ArrowRight, AlertCircle } from 'lucide-react';
import { Button } from '../ui/Button';
import { OrbitLoader } from '../common/OrbitLoader';

interface PromptInputProps {
  promptText: string;
  onPromptChange: (text: string) => void;
  onSubmit: (text: string) => void;
  submittedState: 'idle' | 'loading' | 'submitted' | 'error';
  isLoading?: boolean;
  onReset: () => void;
  providerWarning?: string | null;
}

export const PromptInput: React.FC<PromptInputProps> = ({
  promptText,
  onPromptChange,
  onSubmit,
  submittedState: _submittedState,
  isLoading = false,
  onReset,
  providerWarning,
}) => {
  const [validationError, setValidationError] = useState<string | null>(null);

  const handleSubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (isLoading) return;
    const trimmed = promptText.trim();
    if (!trimmed) {
      setValidationError('Please enter a description of the automation before starting.');
      return;
    }
    setValidationError(null);
    onSubmit(trimmed);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <form onSubmit={handleSubmit} style={{ width: '100%' }}>
      {providerWarning && (
        <div
          className="feedback-banner warning"
          role="status"
          style={{ marginBottom: '16px' }}
        >
          <AlertCircle size={16} style={{ flexShrink: 0, marginTop: '2px' }} />
          <div>{providerWarning}</div>
        </div>
      )}

      <div className="prompt-box">
        <textarea
          id="automation-prompt"
          className="prompt-textarea"
          value={promptText}
          disabled={isLoading}
          onChange={(e) => {
            onPromptChange(e.target.value);
            if (validationError) setValidationError(null);
          }}
          onKeyDown={handleKeyDown}
          placeholder="For example: When a new row is added to Google Sheets, send a Slack notification to #leads, check if priority is high, and create a card in Trello..."
          rows={4}
          aria-label="Describe what you would like to automate"
          aria-invalid={Boolean(validationError)}
          aria-describedby={validationError ? 'prompt-error-msg' : undefined}
        />

        <div className="prompt-footer">
          <div className="prompt-meta">
            <span>{promptText.length} characters</span>
            <span>•</span>
            <span>Press Ctrl+Enter to submit</span>
          </div>

          <div className="prompt-actions">
            {promptText.trim().length > 0 && !isLoading && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => {
                  onPromptChange('');
                  onReset();
                  setValidationError(null);
                }}
              >
                Clear
              </Button>
            )}

            <Button
              type="submit"
              variant="primary"
              size="md"
              disabled={promptText.trim().length === 0 || isLoading}
              icon={isLoading ? <OrbitLoader size="inline" color="currentColor" /> : <ArrowRight size={14} />}
            >
              {isLoading ? 'Generating workflow...' : 'Generate workflow'}
            </Button>
          </div>
        </div>
      </div>

      {validationError && (
        <div
          id="prompt-error-msg"
          className="feedback-banner warning"
          role="alert"
          style={{ marginTop: '-16px', marginBottom: '24px' }}
        >
          <AlertCircle size={16} style={{ flexShrink: 0, marginTop: '2px' }} />
          <div>{validationError}</div>
        </div>
      )}
    </form>
  );
};
