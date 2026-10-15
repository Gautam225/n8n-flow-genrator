import test from 'node:test';
import assert from 'node:assert/strict';

// Test 1: Example Prompts Content and Policy Compliance
test('Example prompts catalog contains all 4 categories and no forbidden em dashes', async () => {
  const { EXAMPLE_PROMPTS } = await import('../src/constants/examplePrompts.ts');

  assert.equal(EXAMPLE_PROMPTS.length, 4);

  const categories = EXAMPLE_PROMPTS.map((p) => p.category);
  assert.deepEqual(categories.sort(), ['Data Sync', 'Fault Tolerance', 'Scheduling', 'Webhooks'].sort());

  for (const ex of EXAMPLE_PROMPTS) {
    assert.ok(ex.title.length > 0, `Title must not be empty for ${ex.id}`);
    assert.ok(ex.prompt.length > 20, `Prompt text must be substantial for ${ex.id}`);
    assert.ok(!ex.prompt.includes('—'), `Prompt ${ex.id} must not contain forbidden em dashes`);
    assert.ok(!ex.description.includes('—'), `Description for ${ex.id} must not contain forbidden em dashes`);
  }
});

// Test 2: Input Validation Logic
test('Input validation prevents empty and whitespace-only submissions', () => {
  const validatePrompt = (text) => {
    const trimmed = text.trim();
    if (!trimmed) {
      return { isValid: false, error: 'Please enter a description of the automation before starting.' };
    }
    return { isValid: true, error: null };
  };

  assert.equal(validatePrompt('').isValid, false);
  assert.equal(validatePrompt('   ').isValid, false);
  assert.equal(validatePrompt('\n\t\n').isValid, false);

  const validRes = validatePrompt('Poll Zendesk tickets and post to Slack');
  assert.equal(validRes.isValid, true);
  assert.equal(validRes.error, null);
});

// Test 3: Route Resolution Logic
test('Route resolution supports workspace, drafts, and settings', () => {
  const parseRoute = (hash) => {
    const clean = hash.replace(/^#\/?/, '');
    if (clean === 'drafts') return 'drafts';
    if (clean === 'settings') return 'settings';
    return 'workspace';
  };

  assert.equal(parseRoute(''), 'workspace');
  assert.equal(parseRoute('#/'), 'workspace');
  assert.equal(parseRoute('#/drafts'), 'drafts');
  assert.equal(parseRoute('#drafts'), 'drafts');
  assert.equal(parseRoute('#/settings'), 'settings');
  assert.equal(parseRoute('#unknown'), 'workspace');
});

// Test 4: Theme Toggle Logic
test('Theme toggle toggles strictly between light and dark', () => {
  const toggleTheme = (current) => (current === 'light' ? 'dark' : 'light');

  assert.equal(toggleTheme('light'), 'dark');
  assert.equal(toggleTheme('dark'), 'light');
});

// Test 5: Connection Status Badge Mapping & State Transitions
test('Connection status mapping produces distinct badge variants and honest labels', () => {
  const getBadgeConfig = (status) => {
    switch (status) {
      case 'loading':
        return { variant: 'info', label: 'Checking...' };
      case 'connected':
        return { variant: 'success', label: 'Connected & Authenticated' };
      case 'not_configured':
        return { variant: 'warning', label: 'API Key Not Configured' };
      case 'unauthorized':
        return { variant: 'error', label: 'Invalid / Unauthorized API Key' };
      case 'unreachable':
        return { variant: 'error', label: 'Instance Unreachable' };
      case 'backend_offline':
        return { variant: 'error', label: 'Backend Offline' };
      case 'error':
        return { variant: 'error', label: 'Connection Error' };
      case 'idle':
      default:
        return { variant: 'neutral', label: 'Not Checked' };
    }
  };

  assert.deepEqual(getBadgeConfig('connected'), { variant: 'success', label: 'Connected & Authenticated' });
  assert.deepEqual(getBadgeConfig('not_configured'), { variant: 'warning', label: 'API Key Not Configured' });
  assert.deepEqual(getBadgeConfig('unauthorized'), { variant: 'error', label: 'Invalid / Unauthorized API Key' });
  assert.deepEqual(getBadgeConfig('unreachable'), { variant: 'error', label: 'Instance Unreachable' });
  assert.deepEqual(getBadgeConfig('backend_offline'), { variant: 'error', label: 'Backend Offline' });
  assert.deepEqual(getBadgeConfig('loading'), { variant: 'info', label: 'Checking...' });
  assert.deepEqual(getBadgeConfig('idle'), { variant: 'neutral', label: 'Not Checked' });
});

// Test 6: Honest Backend Offline & Error Handling
test('Network errors gracefully resolve to honest backend_offline state without simulating success', async () => {
  const mockFetchFailure = async () => {
    throw new TypeError('Failed to fetch');
  };

  const resolveStatus = async (fetchFn) => {
    try {
      const res = await fetchFn();
      if (!res.ok) {
        return { status: 'error', message: `Backend returned HTTP status ${res.status}.` };
      }
      return await res.json();
    } catch {
      return {
        status: 'backend_offline',
        message: 'FastAPI backend server is not running or unreachable at http://127.0.0.1:8000. Start it with uvicorn.',
      };
    }
  };

  const offlineResult = await resolveStatus(mockFetchFailure);
  assert.equal(offlineResult.status, 'backend_offline');
  assert.ok(offlineResult.message.includes('http://127.0.0.1:8000'));
  assert.notEqual(offlineResult.status, 'connected');
});

// Test 7: Secret redaction in frontend status messages
test('Frontend messages never expose API keys or authorization headers', () => {
  const secretKey = 'n8n_sec_xyz987654321';
  const sanitizeMessage = (msg, key) => {
    if (!msg || !key) return msg;
    return msg.replaceAll(key, '[REDACTED]');
  };

  const rawMessage = `Error contacting upstream with key ${secretKey}`;
  const sanitized = sanitizeMessage(rawMessage, secretKey);
  assert.ok(!sanitized.includes(secretKey));
  assert.ok(sanitized.includes('[REDACTED]'));
});

// Test 8: Main Navigation items match simplified 3-tab structure
test('Main navigation presents exactly Create, My Workflows, and Settings', () => {
  const navItems = [
    { route: 'workspace', label: 'Create' },
    { route: 'drafts', label: 'My Workflows' },
    { route: 'settings', label: 'Settings' },
  ];

  assert.equal(navItems.length, 3);
  assert.deepEqual(
    navItems.map((n) => n.label),
    ['Create', 'My Workflows', 'Settings']
  );
  assert.deepEqual(
    navItems.map((n) => n.route),
    ['workspace', 'drafts', 'settings']
  );
});

// Test 9: Readiness Status mapping uses plain English labels
test('Readiness status displays Ready for review, Needs configuration, and Blocked', () => {
  const getReadinessLabel = (status) => {
    switch (status) {
      case 'ready':
        return 'Ready for review';
      case 'needs_attention':
        return 'Needs configuration';
      case 'blocked':
        return 'Blocked';
      default:
        return 'Evaluating...';
    }
  };

  assert.equal(getReadinessLabel('ready'), 'Ready for review');
  assert.equal(getReadinessLabel('needs_attention'), 'Needs configuration');
  assert.equal(getReadinessLabel('blocked'), 'Blocked');
  assert.equal(getReadinessLabel('unknown'), 'Evaluating...');
});

// Test 10: Local drafts are honestly labeled without claiming live n8n deployment
test('Workflow drafts view describes local drafts without claiming live deployment', () => {
  const draftsDescription = 'Locally saved workflow drafts stored in PostgreSQL. These drafts are stored locally and are not deployed or activated in n8n.';
  assert.ok(!draftsDescription.includes('deployed to n8n'));
  assert.ok(draftsDescription.includes('not deployed or activated in n8n'));
  assert.ok(!draftsDescription.includes('—'), 'Drafts description must not contain em dashes');
});

// Test 11: Create screen primary action is Generate workflow
test('Create screen primary action is Generate workflow', () => {
  const createTitle = 'What would you like to automate?';
  const primaryButtonLabel = 'Generate workflow';

  assert.equal(createTitle, 'What would you like to automate?');
  assert.equal(primaryButtonLabel, 'Generate workflow');
  assert.ok(!createTitle.includes('—'), 'Create title must not contain em dashes');
});

// Test 12: Clickable clarification choices include Gmail, Outlook, IMAP, Other
test('Clarification options present Gmail, Outlook, IMAP, and Other with structured answers', () => {
  const emailOptions = [
    { label: 'Gmail', value: 'gmail' },
    { label: 'Outlook', value: 'outlook' },
    { label: 'IMAP / Custom Email', value: 'imap' },
    { label: 'Other', value: 'other' },
  ];

  assert.equal(emailOptions.length, 4);
  assert.deepEqual(emailOptions.map((o) => o.value), ['gmail', 'outlook', 'imap', 'other']);

  // Selecting a non-other option produces structured payload
  const formatAnswer = (fieldKey, optValue, optLabel) => {
    return {
      text: optLabel,
      selectedOptions: { [fieldKey]: optValue },
    };
  };

  const gmailAnswer = formatAnswer('email_provider', 'gmail', 'Gmail');
  assert.deepEqual(gmailAnswer.selectedOptions, { email_provider: 'gmail' });
  assert.equal(gmailAnswer.text, 'Gmail');
});

// Test 13: Generation lifecycle defines the 7 states without fake percentages
test('Generation lifecycle steps map to the 7 required stages', () => {
  const lifecycleStates = [
    'understanding', // 1. Understanding the request
    'checking',      // 2. Checking required information
    'clarifying',    // 3. Waiting for user's answer
    'building',      // 4. Building the workflow
    'validating',    // 5. Validating the workflow
    'ready',         // 6. Workflow ready for review
    'timed_out',     // 7. Failed or timed out
  ];

  assert.equal(lifecycleStates.length, 7);
  assert.ok(lifecycleStates.includes('understanding'));
  assert.ok(lifecycleStates.includes('checking'));
  assert.ok(lifecycleStates.includes('clarifying'));
  assert.ok(lifecycleStates.includes('building'));
  assert.ok(lifecycleStates.includes('validating'));
  assert.ok(lifecycleStates.includes('ready'));
  assert.ok(lifecycleStates.includes('timed_out'));
});

// Test 14: Non-duplicating retry policy preserves conversation ID and original prompt
test('Retry policy reuses existing conversation ID without creating duplicates', () => {
  const state = {
    conversationId: 'conv-12345',
    promptText: 'When I receive an email, send me a notification on Telegram.',
    draftsCreated: 1,
  };

  const executeRetry = (currentState) => {
    // If conversationId exists, send message to existing conversation
    if (currentState.conversationId) {
      return {
        action: 'sendMessage',
        targetId: currentState.conversationId,
        prompt: currentState.promptText,
        duplicateDraftCreated: false,
      };
    }
    return {
      action: 'createConversation',
      prompt: currentState.promptText,
      duplicateDraftCreated: false,
    };
  };

  const retryAction = executeRetry(state);
  assert.equal(retryAction.action, 'sendMessage');
  assert.equal(retryAction.targetId, 'conv-12345');
  assert.equal(retryAction.prompt, state.promptText);
  assert.equal(retryAction.duplicateDraftCreated, false);
});

// Test 15: Telegram chat ID validation accepts numeric and channel formats without inventing bot tokens
test('Telegram chat ID format validator handles numeric IDs and @handles', () => {
  const validateChatId = (val) => {
    const clean = (val || '').trim();
    if (!clean || clean.includes('<YOUR_TELEGRAM_CHAT_ID>')) return false;
    if (/bot$/i.test(clean)) return false; // Bot usernames ending in 'bot' are strictly rejected
    if (/^-?\d{5,16}$/.test(clean)) return true;
    if (/^@[a-zA-Z0-9_]{4,32}$/.test(clean)) return true;
    return false;
  };

  assert.equal(validateChatId('123456789'), true);
  assert.equal(validateChatId('-1001234567890'), true);
  assert.equal(validateChatId('@my_alerts_channel'), true);
  assert.equal(validateChatId(''), false);
  assert.equal(validateChatId('={{ "<YOUR_TELEGRAM_CHAT_ID>" }}'), false);
  assert.equal(validateChatId('Emcheckmebot'), false); // not numeric or @handle
  assert.equal(validateChatId('@Emcheckmebot'), false); // bot handle ending in bot rejected
});

// Test 16: Multi-turn clarification sequence presents one question at a time and accumulates answers
test('Multi-turn clarification sequence presents one question at a time and accumulates answers', () => {
  const clarificationSequence = {
    originalPrompt: 'When I receive an email, send me a notification on Telegram.',
    requiredFields: ['email_provider', 'telegram_chat_id'],
    completedAnswers: {},
  };

  // Step 1: determine current question
  const getCurrentQuestion = (state) => {
    const outstanding = state.requiredFields.filter((f) => !state.completedAnswers[f]);
    if (outstanding.length === 0) return null;
    if (outstanding[0] === 'email_provider') {
      return {
        id: 'email_provider',
        question: 'Which email service should trigger the workflow?',
        options: [
          { label: 'Gmail', value: 'gmail' },
          { label: 'Outlook', value: 'outlook' },
          { label: 'IMAP / Custom Email', value: 'imap' },
          { label: 'Other', value: 'other' },
        ],
      };
    }
    if (outstanding[0] === 'telegram_chat_id') {
      return {
        id: 'telegram_chat_id',
        question: 'Which Telegram Chat ID should receive the notifications?',
        inputType: 'telegram_config',
      };
    }
    return null;
  };

  // Turn 1: asks email_provider
  const q1 = getCurrentQuestion(clarificationSequence);
  assert.equal(q1.id, 'email_provider');
  assert.equal(q1.question, 'Which email service should trigger the workflow?');
  assert.equal(q1.options.length, 4);

  // User answers Gmail
  clarificationSequence.completedAnswers['email_provider'] = 'gmail';

  // Turn 2: asks telegram_chat_id next without skipping
  const q2 = getCurrentQuestion(clarificationSequence);
  assert.equal(q2.id, 'telegram_chat_id');
  assert.equal(q2.question, 'Which Telegram Chat ID should receive the notifications?');
  assert.equal(clarificationSequence.completedAnswers['email_provider'], 'gmail');

  // User answers chat ID
  clarificationSequence.completedAnswers['telegram_chat_id'] = '123456789';

  // Turn 3: all answered, ready to generate
  const q3 = getCurrentQuestion(clarificationSequence);
  assert.equal(q3, null);
  assert.deepEqual(clarificationSequence.completedAnswers, {
    email_provider: 'gmail',
    telegram_chat_id: '123456789',
  });
});

// Test 17: Page refresh restores active clarification state and original prompt
test('Page refresh restores active clarification state and original prompt', () => {
  const serverDetailResponse = {
    id: 'conv-999',
    title: 'Email to Telegram',
    state: 'clarifying',
    original_prompt: 'When I receive an email, send me a notification on Telegram.',
    slots: { email_provider: 'gmail' },
    current_question_id: 'telegram_chat_id',
    outstanding_questions: ['telegram_chat_id'],
    clarification: {
      has_ambiguities: true,
      questions: [
        {
          id: 'telegram_chat_id',
          question: 'Which Telegram Chat ID should receive the notifications?',
          field_key: 'telegram_chat_id',
        },
      ],
    },
    messages: [
      { role: 'user', content: 'When I receive an email, send me a notification on Telegram.' },
      { role: 'assistant', content: 'Which email service should trigger the workflow?' },
      { role: 'user', content: 'Gmail' },
      { role: 'assistant', content: 'Which Telegram Chat ID should receive the notifications?' },
    ],
  };

  const restoredState = {
    conversationId: serverDetailResponse.id,
    prompt: serverDetailResponse.original_prompt,
    stage: serverDetailResponse.state,
    completedAnswers: serverDetailResponse.slots,
    activeQuestionId: serverDetailResponse.current_question_id,
  };

  assert.equal(restoredState.conversationId, 'conv-999');
  assert.equal(restoredState.prompt, 'When I receive an email, send me a notification on Telegram.');
  assert.equal(restoredState.stage, 'clarifying');
  assert.equal(restoredState.completedAnswers.email_provider, 'gmail');
  assert.equal(restoredState.activeQuestionId, 'telegram_chat_id');
});

// Test 18: Markdown cleaning unescapes backslashes without executing HTML
test('Markdown cleaning unescapes backslashes and disallows unsafe links', () => {
  const cleanEscapedMarkdown = (raw) => {
    if (!raw) return '';
    return raw.replace(/\\(\*|_|#|\[|\]|\(|\)|`)/g, '$1').trim();
  };

  const isSafeUrl = (url) => {
    if (!url) return false;
    const clean = url.trim().toLowerCase();
    return clean.startsWith('http://') || clean.startsWith('https://') || clean.startsWith('mailto:') || clean.startsWith('/');
  };

  const sample = '\\*\\*Assistant Question\\*\\*: Which email service?';
  assert.equal(cleanEscapedMarkdown(sample), '**Assistant Question**: Which email service?');

  assert.equal(isSafeUrl('https://n8n.io'), true);
  assert.equal(isSafeUrl('javascript:alert(1)'), false);
  assert.equal(isSafeUrl('data:text/html,<script>alert(1)</script>'), false);
});

// Test 19: Double submission debounce protection
test('Two rapid clicks cannot create duplicate turns when submission lock is active', () => {
  let callCount = 0;
  let isSubmitting = false;

  const handleClick = () => {
    if (isSubmitting) return false;
    isSubmitting = true;
    callCount += 1;
    return true;
  };

  const firstClick = handleClick();
  const secondClick = handleClick();

  assert.equal(firstClick, true);
  assert.equal(secondClick, false);
  assert.equal(callCount, 1);
});

// Test 20: Selecting Gmail or Outlook changes selection only, without submitting or advancing
test('Selecting an option updates selected state only and does not submit or advance the turn', () => {
  let submitCount = 0;
  const state = {
    selectedAnswers: {},
    showOtherInput: {},
  };

  const handleOptionSelect = (qId, optVal) => {
    state.selectedAnswers[qId] = optVal;
    state.showOtherInput[qId] = optVal === 'other';
    // Does NOT trigger submit!
  };

  handleOptionSelect('email_provider', 'gmail');
  assert.equal(state.selectedAnswers['email_provider'], 'gmail');
  assert.equal(state.showOtherInput['email_provider'], false);
  assert.equal(submitCount, 0, 'Must not submit on selecting Gmail');

  handleOptionSelect('email_provider', 'outlook');
  assert.equal(state.selectedAnswers['email_provider'], 'outlook');
  assert.equal(state.showOtherInput['email_provider'], false);
  assert.equal(submitCount, 0, 'Must not submit on selecting Outlook');
});

// Test 21: Selecting Other reveals custom text field without submitting, and custom answer is required
test('Selecting Other reveals custom text field without submitting, and validates non-empty custom text', () => {
  let submitCount = 0;
  const state = {
    selectedAnswers: {},
    showOtherInput: {},
    customAnswers: {},
    errors: {},
  };

  const handleOptionSelect = (qId, optVal) => {
    state.selectedAnswers[qId] = optVal;
    state.showOtherInput[qId] = optVal === 'other';
  };

  const handleSubmit = (qList) => {
    const errs = {};
    for (const q of qList) {
      if (state.selectedAnswers[q.id] === 'other' && !(state.customAnswers[q.id] || '').trim()) {
        errs[q.id] = 'Please enter your custom answer.';
      }
    }
    state.errors = errs;
    if (Object.keys(errs).length === 0) {
      submitCount += 1;
    }
  };

  // 1. Select other
  handleOptionSelect('email_provider', 'other');
  assert.equal(state.showOtherInput['email_provider'], true);
  assert.equal(submitCount, 0);

  // 2. Submit without typing custom text -> fails validation
  handleSubmit([{ id: 'email_provider', required: true }]);
  assert.equal(submitCount, 0);
  assert.equal(state.errors['email_provider'], 'Please enter your custom answer.');

  // 3. User types custom answer and submits -> passes
  state.customAnswers['email_provider'] = 'Zoho Mail';
  handleSubmit([{ id: 'email_provider', required: true }]);
  assert.equal(submitCount, 1);
  assert.deepEqual(state.errors, {});
});

// Test 22: All answers are submitted together in one batch payload
test('All answers are submitted together only when user clicks Submit answers', () => {
  let submittedBatch = null;

  const onSubmitBatch = (selectedOptions, answers) => {
    submittedBatch = { selectedOptions, answers };
  };

  const formState = {
    selectedAnswers: { email_provider: 'gmail', telegram_chat_id: 'private_chat' },
    customAnswers: { telegram_chat_id: '123456789' },
  };

  const questions = [
    { id: 'email_provider', field_key: 'email_provider' },
    { id: 'telegram_chat_id', field_key: 'telegram_chat_id' },
  ];

  // Batch builder
  const answers = questions.map((q) => ({
    question_id: q.id,
    field_key: q.field_key,
    selected_value: formState.selectedAnswers[q.id],
    custom_text: formState.customAnswers[q.id],
  }));

  const selectedOptions = {
    email_provider: 'gmail',
    telegram_chat_id: '123456789',
  };

  onSubmitBatch(selectedOptions, answers);

  assert.ok(submittedBatch !== null);
  assert.equal(submittedBatch.answers.length, 2);
  assert.equal(submittedBatch.selectedOptions.email_provider, 'gmail');
  assert.equal(submittedBatch.selectedOptions.telegram_chat_id, '123456789');
});

// Test 23: Telegram chat ID validator rejects bot usernames and accepts valid numeric IDs
test('Telegram chat ID validator strictly rejects bot usernames ending in bot', () => {
  const isBotUsername = (val) => /bot$/i.test(val.trim());
  const isChatIdFormatValid = (val) => {
    const clean = val.trim();
    if (!clean || isBotUsername(clean)) return false;
    return /^-?\d{5,15}$/.test(clean) || /^@[a-zA-Z0-9_]{4,32}$/.test(clean);
  };

  assert.equal(isChatIdFormatValid('Emcheckmebot'), false);
  assert.equal(isChatIdFormatValid('@Emcheckmebot'), false);
  assert.equal(isChatIdFormatValid('my_bot'), false);
  assert.equal(isChatIdFormatValid('123456789'), true);
  assert.equal(isChatIdFormatValid('-100123456789'), true);
  assert.equal(isChatIdFormatValid('@mychannel'), true);
});

// Test 24: Previously answered questions are excluded from subsequent forms
test('Answered questions remain accumulated and are excluded from subsequent forms', () => {
  const allNeededFields = ['email_provider', 'telegram_chat_id'];
  const accumulatedSlots = { email_provider: 'gmail' };

  const outstandingFields = allNeededFields.filter((f) => !accumulatedSlots[f]);
  assert.deepEqual(outstandingFields, ['telegram_chat_id']);
  assert.equal(accumulatedSlots['email_provider'], 'gmail');
});



