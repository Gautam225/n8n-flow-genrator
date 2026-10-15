import React from 'react';
import {
  Clock,
  Webhook,
  MessageSquare,
  Database,
  Globe,
  Code2,
  GitBranch,
  Mail,
  Send,
  FileSpreadsheet,
  Layers,
  Bot,
  Zap,
} from 'lucide-react';

export function getNodeIcon(nodeType: string, size: number = 15): React.ReactElement {
  const lower = (nodeType || '').toLowerCase();
  if (lower.includes('schedule') || lower.includes('cron') || lower.includes('interval')) {
    return <Clock size={size} style={{ color: 'var(--brand-primary, #EA580C)' }} />;
  }
  if (lower.includes('webhook')) {
    return <Webhook size={size} style={{ color: 'var(--state-info, #0284C7)' }} />;
  }
  if (lower.includes('telegram')) {
    return <Send size={size} style={{ color: '#0284C7' }} />;
  }
  if (lower.includes('slack')) {
    return <MessageSquare size={size} style={{ color: '#E01E5A' }} />;
  }
  if (lower.includes('sheets') || lower.includes('spreadsheet') || lower.includes('excel')) {
    return <FileSpreadsheet size={size} style={{ color: 'var(--state-success, #10B981)' }} />;
  }
  if (lower.includes('postgres') || lower.includes('mysql') || lower.includes('database') || lower.includes('sql')) {
    return <Database size={size} style={{ color: '#336791' }} />;
  }
  if (lower.includes('http') || lower.includes('fetch') || lower.includes('rest') || lower.includes('api')) {
    return <Globe size={size} style={{ color: 'var(--state-success, #10B981)' }} />;
  }
  if (lower.includes('code') || lower.includes('function') || lower.includes('javascript')) {
    return <Code2 size={size} style={{ color: 'var(--state-warning, #F59E0B)' }} />;
  }
  if (lower.includes('if') || lower.includes('switch') || lower.includes('filter') || lower.includes('branch')) {
    return <GitBranch size={size} style={{ color: 'var(--state-info, #0284C7)' }} />;
  }
  if (lower.includes('mail') || lower.includes('gmail') || lower.includes('email') || lower.includes('outlook')) {
    return <Mail size={size} style={{ color: '#EA4335' }} />;
  }
  if (lower.includes('openai') || lower.includes('ai') || lower.includes('agent')) {
    return <Bot size={size} style={{ color: 'var(--brand-primary, #EA580C)' }} />;
  }
  if (lower.includes('trigger')) {
    return <Zap size={size} style={{ color: 'var(--brand-primary, #EA580C)' }} />;
  }
  return <Layers size={size} style={{ color: 'var(--text-secondary, #9CA3AF)' }} />;
}

export function formatShortNodeType(nodeType: string): string {
  if (!nodeType) return 'Custom Node';
  return nodeType.replace(/^n8n-nodes-base\./, '');
}
