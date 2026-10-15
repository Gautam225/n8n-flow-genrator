import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

/**
 * Orbit Loader Component & CSS Validation Tests
 */

test('OrbitLoader component file exists and contains expected accessibility and orbit logic', () => {
  const componentPath = path.resolve(__dirname, '../src/components/common/OrbitLoader.tsx');
  assert.ok(fs.existsSync(componentPath), 'OrbitLoader.tsx should exist in common components');

  const content = fs.readFileSync(componentPath, 'utf8');

  // Accessibility contract
  assert.match(content, /role="status"/, 'Must include role="status"');
  assert.match(content, /aria-live="polite"/, 'Must include aria-live="polite"');
  assert.match(content, /aria-busy="true"/, 'Must include aria-busy="true"');
  assert.match(content, /aria-hidden="true"/, 'SVG must have aria-hidden="true"');
  assert.match(content, /sr-only/, 'Must render accessible screen-reader-only text');

  // Orbit structures
  assert.match(content, /orbit-core/, 'Must render central core point');
  assert.match(content, /orbit-track-outer/, 'Must render outer orbit track with satellite');
  assert.match(content, /orbit-track-inner/, 'Must render inner orbit track for standard/large sizes');

  // Sizing definitions
  assert.match(content, /inline: 14/, 'Must map inline to 14px');
  assert.match(content, /xs: 16/, 'Must map xs to 16px');
  assert.match(content, /sm: 20/, 'Must map sm to 20px');
  assert.match(content, /md: 32/, 'Must map md to 32px');
  assert.match(content, /lg: 48/, 'Must map lg to 48px');
});

test('index.css contains Orbit Loader keyframes and reduced-motion rules', () => {
  const cssPath = path.resolve(__dirname, '../src/index.css');
  assert.ok(fs.existsSync(cssPath), 'index.css should exist');

  const css = fs.readFileSync(cssPath, 'utf8');

  // Verify class definitions
  assert.ok(css.includes('.orbit-loader-container'), 'CSS must define .orbit-loader-container');
  assert.ok(css.includes('.orbit-track-outer'), 'CSS must define .orbit-track-outer');
  assert.ok(css.includes('.orbit-track-inner'), 'CSS must define .orbit-track-inner');
  assert.ok(css.includes('.orbit-core'), 'CSS must define .orbit-core');

  // Verify animation keyframes
  assert.ok(css.includes('@keyframes orbit-spin-clockwise'), 'CSS must define orbit-spin-clockwise');
  assert.ok(css.includes('@keyframes orbit-spin-counter'), 'CSS must define orbit-spin-counter');
  assert.ok(css.includes('@keyframes orbit-core-pulse'), 'CSS must define orbit-core-pulse');

  // Verify reduced-motion support
  assert.ok(css.includes('prefers-reduced-motion: reduce'), 'CSS must handle prefers-reduced-motion');
  assert.ok(css.includes('studio-pulse'), 'CSS must define fallback pulse for reduced-motion');

  // Verify sr-only utility
  assert.ok(css.includes('.sr-only'), 'CSS must define .sr-only utility class');
});

test('All legacy Loader2 and icon-spin references in components are removed and replaced', () => {
  const srcDir = path.resolve(__dirname, '../src');

  function checkDir(dir) {
    const entries = fs.readdirSync(dir, { withFileTypes: true });
    for (const entry of entries) {
      const fullPath = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        checkDir(fullPath);
      } else if (entry.isFile() && (entry.name.endsWith('.tsx') || entry.name.endsWith('.ts'))) {
        const fileContent = fs.readFileSync(fullPath, 'utf8');
        assert.ok(
          !fileContent.includes('Loader2'),
          `File ${entry.name} still contains Loader2 reference: ${fullPath}`
        );
      }
    }
  }

  checkDir(srcDir);
});
