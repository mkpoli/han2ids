#!/usr/bin/env node
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, copyFileSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, basename } from 'node:path';
import { spawnSync } from 'node:child_process';
import { test } from 'node:test';

test('checks translation keys in nested application modules', () => {
  const dir = mkdtempSync(join(tmpdir(), 'han2ids-i18n-'));
  try {
    mkdirSync(join(dir, 'static', 'feature'), { recursive: true });
    copyFileSync(new URL('../check-i18n.mjs', import.meta.url), join(dir, 'check-i18n.mjs'));
    copyFileSync(new URL('../static/i18n.js', import.meta.url), join(dir, 'static', 'i18n.js'));
    writeFileSync(join(dir, 'static', 'index.html'), '<html></html>');
    const module = join(dir, 'static', 'feature', 'new.js');
    writeFileSync(module, "t('missing.translation');\n");
    const bad = spawnSync(process.execPath, [join(dir, 'check-i18n.mjs')], { encoding: 'utf8' });
    assert.equal(bad.status, 1);
    assert.match(bad.stderr, /page uses unknown key missing\.translation/);
    writeFileSync(module, "t('meta.title');\n");
    const good = spawnSync(process.execPath, [join(dir, 'check-i18n.mjs')], { encoding: 'utf8' });
    assert.equal(good.status, 0, good.stderr);
  } finally {
    if (basename(dir).startsWith('han2ids-i18n-') && dir.startsWith(`${tmpdir()}/`)) {
      rmSync(dir, { recursive: true, force: true });
    }
  }
});
