import type { ExamplePrompt } from '../types';

export const EXAMPLE_PROMPTS: ExamplePrompt[] = [
  {
    id: 'ex-schedule',
    title: 'Daily Customer Digest',
    category: 'Scheduling',
    description: 'Scheduled Postgres query aggregated and dispatched to Slack.',
    prompt:
      'Every weekday at 08:30 UTC, query the PostgreSQL database for orders pending fulfillment, calculate daily totals, and send a structured summary message to the Slack #operations channel.',
  },
  {
    id: 'ex-webhook',
    title: 'Stripe Payment Verification',
    category: 'Webhooks',
    description: 'Listen for payment webhooks, branch on status, and log receipt.',
    prompt:
      'Listen for incoming Stripe payment webhooks, verify the event type with an If condition, insert verified receipts into PostgreSQL, and send a confirmation email for successful transactions.',
  },
  {
    id: 'ex-sync',
    title: 'Shopify Batch Inventory Sync',
    category: 'Data Sync',
    description: 'Batch iteration loop updating 50 items at a time.',
    prompt:
      'Fetch updated product records from the Shopify REST API every hour, process them in batches of 50 using a loop, update local inventory counts in PostgreSQL, and log the completed batch count.',
  },
  {
    id: 'ex-fault',
    title: 'Fault-Tolerant Exchange Rates',
    category: 'Fault Tolerance',
    description: 'API polling with automatic retries and error sub-workflow.',
    prompt:
      'Fetch currency exchange rates from an external REST API every 15 minutes. On transient network failures, retry 3 times with exponential backoff. If retries fail, route the execution to an alert workflow.',
  },
];
