#!/usr/bin/env node
// Checks that every locale has the same keys and that the page uses only those keys.
import { readFileSync } from 'node:fs'
import { DEFAULT_LOCALE, LOCALES } from './static/i18n.js'

const failures = []
const keys = Object.keys(LOCALES[DEFAULT_LOCALE].messages)
const base = LOCALES[DEFAULT_LOCALE].messages
const placeholders = text => [...text.matchAll(/\{([a-z]+)\}/g)].map(match => match[1]).sort().join(',')

for (const key of keys) {
  if (!base[key]?.trim()) failures.push(`${DEFAULT_LOCALE}: ${key} is empty`)
}

for (const [locale, entry] of Object.entries(LOCALES)) {
  const messages = entry.messages
  for (const key of keys) {
    if (!(key in messages)) failures.push(`${locale}: missing ${key}`)
    else if (!messages[key]?.trim()) failures.push(`${locale}: ${key} is empty`)
    else if (placeholders(messages[key]) !== placeholders(base[key])) {
      failures.push(`${locale}: ${key} has different placeholders`)
    }
  }
  for (const key of Object.keys(messages)) {
    if (!(key in base)) failures.push(`${locale}: extra ${key}`)
  }
}

const html = readFileSync(new URL('./static/index.html', import.meta.url), 'utf8')
const script = readFileSync(new URL('./static/app.js', import.meta.url), 'utf8')
const used = new Set()
for (const match of html.matchAll(/data-i18n(?:-aria|-title|-alt)?="([^"]+)"/g)) used.add(match[1])
for (const match of script.matchAll(/(?<![A-Za-z0-9_$])t\('([^']+)'/g)) used.add(match[1])
for (const match of script.matchAll(/(?:titleKey|detailKey): '([^']+)'/g)) used.add(match[1])
// Keys chosen in ternaries, such as the network/read error pair, still appear as literals.
for (const key of keys) if (script.includes(`'${key}'`)) used.add(key)
for (const key of used) {
  if (!(key in base)) failures.push(`page uses unknown key ${key}`)
}

console.log(`${Object.keys(LOCALES).length} locales, ${keys.length} keys, ${used.size} keys used by the page`)
if (failures.length) {
  for (const failure of failures) console.error(failure)
  process.exit(1)
}
