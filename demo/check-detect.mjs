#!/usr/bin/env node
// Checks that the glyph detector finds every cell of the sample sheets and no more.
import { inflateSync } from 'node:zlib'
import { readFileSync } from 'node:fs'
import { analysePixels } from './static/detect.js'

const CHANNELS = { 0: 1, 2: 3, 4: 2, 6: 4 }
const failures = []

/** The RGBA pixels of an 8-bit non-interlaced PNG. */
function readPng(path) {
  const file = readFileSync(path)
  let at = 8
  let header = null
  const parts = []
  while (at < file.length) {
    const length = file.readUInt32BE(at)
    const type = file.toString('ascii', at + 4, at + 8)
    const body = file.subarray(at + 8, at + 8 + length)
    if (type === 'IHDR') {
      header = { width: body.readUInt32BE(0), height: body.readUInt32BE(4), depth: body[8], colour: body[9], interlace: body[12] }
    } else if (type === 'IDAT') parts.push(body)
    else if (type === 'IEND') break
    at += length + 12
  }
  if (!header) throw new Error(`${path}: no IHDR`)
  if (header.depth !== 8 || header.interlace || !CHANNELS[header.colour]) {
    throw new Error(`${path}: unsupported PNG (depth ${header.depth}, colour ${header.colour})`)
  }

  const { width, height, colour } = header
  const channels = CHANNELS[colour]
  const stride = width * channels
  const raw = inflateSync(Buffer.concat(parts))
  const lines = Buffer.alloc(height * stride)

  for (let y = 0; y < height; y += 1) {
    const filter = raw[y * (stride + 1)]
    const source = raw.subarray(y * (stride + 1) + 1, y * (stride + 1) + 1 + stride)
    const line = lines.subarray(y * stride, (y + 1) * stride)
    const above = y ? lines.subarray((y - 1) * stride, y * stride) : null
    for (let x = 0; x < stride; x += 1) {
      const left = x >= channels ? line[x - channels] : 0
      const up = above ? above[x] : 0
      const corner = above && x >= channels ? above[x - channels] : 0
      let value = source[x]
      if (filter === 1) value += left
      else if (filter === 2) value += up
      else if (filter === 3) value += (left + up) >> 1
      else if (filter === 4) {
        const estimate = left + up - corner
        const dLeft = Math.abs(estimate - left)
        const dUp = Math.abs(estimate - up)
        const dCorner = Math.abs(estimate - corner)
        value += dLeft <= dUp && dLeft <= dCorner ? left : dUp <= dCorner ? up : corner
      }
      line[x] = value & 0xff
    }
  }

  const data = new Uint8ClampedArray(width * height * 4)
  for (let index = 0; index < width * height; index += 1) {
    const source = index * channels
    const target = index * 4
    if (channels >= 3) {
      data[target] = lines[source]
      data[target + 1] = lines[source + 1]
      data[target + 2] = lines[source + 2]
      data[target + 3] = channels === 4 ? lines[source + 3] : 255
    } else {
      data[target] = data[target + 1] = data[target + 2] = lines[source]
      data[target + 3] = channels === 2 ? lines[source + 1] : 255
    }
  }
  return { data, width, height }
}

function raster(name) {
  return readPng(new URL(`./static/samples/${name}`, import.meta.url))
}

function check(name, boxes, expected, shape) {
  if (boxes.length !== expected) {
    failures.push(`${name}: ${boxes.length} boxes, expected ${expected}`)
    return
  }
  for (const [index, box] of boxes.entries()) {
    if (box.w <= 0 || box.h <= 0 || box.x < 0 || box.y < 0 || box.x + box.w > 1.001 || box.y + box.h > 1.001) {
      failures.push(`${name}: box ${index + 1} is outside the image`)
    }
  }
  for (let first = 0; first < boxes.length; first += 1) {
    for (let second = first + 1; second < boxes.length; second += 1) {
      const a = boxes[first]
      const b = boxes[second]
      const overlap = Math.max(0, Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x))
        * Math.max(0, Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y))
      if (overlap > 0) failures.push(`${name}: boxes ${first + 1} and ${second + 1} overlap`)
    }
  }
  if (shape) shape(boxes)
}

// A single glyph stays one box, whatever its structure.
check('sample-yi.png', analysePixels(raster('sample-yi.png')).boxes, 1)
check('glyph-chuan.png', analysePixels(raster('glyph-chuan.png')).boxes, 1)

// Two tiers and two halves per row, in reading order.
check('sheet-grid.png', analysePixels(raster('sheet-grid.png')).boxes, 4, boxes => {
  // 明 曼 over 川 二: one box per cell, each inside its own quadrant.
  const quadrants = [[0, 0], [1, 0], [0, 1], [1, 1]]
  for (const [index, box] of boxes.entries()) {
    const [column, row] = quadrants[index]
    const middle = { x: box.x + box.w / 2, y: box.y + box.h / 2 }
    if (Math.floor(middle.x * 2) !== column || Math.floor(middle.y * 2) !== row) {
      failures.push(`sheet-grid.png: box ${index + 1} is not in cell ${column + 1},${row + 1}`)
    }
    if (Math.max(box.w, box.h) < 0.2) failures.push(`sheet-grid.png: box ${index + 1} is smaller than a glyph`)
  }
})

check('sheet-row.png', analysePixels(raster('sheet-row.png')).boxes, 4, boxes => {
  for (let index = 1; index < boxes.length; index += 1) {
    if (boxes[index].x <= boxes[index - 1].x) failures.push('sheet-row.png: boxes are not left to right')
  }
})

// A speck in a gutter is not a glyph.
const speckled = raster('sheet-grid.png')
for (let y = 0; y < 2; y += 1) {
  for (let x = 0; x < 2; x += 1) {
    const offset = ((Math.round(speckled.height / 2) + y) * speckled.width + 10 + x) * 4
    speckled.data[offset] = speckled.data[offset + 1] = speckled.data[offset + 2] = 0
  }
}
check('sheet-grid.png with a speck', analysePixels(speckled).boxes, 4)

// A blank border does not move the cut.
const padded = { width: 560, height: 560, data: new Uint8ClampedArray(560 * 560 * 4).fill(255) }
const source = raster('sheet-grid.png')
for (let y = 0; y < source.height; y += 1) {
  for (let x = 0; x < source.width; x += 1) {
    const from = (y * source.width + x) * 4
    const to = ((y + 40) * padded.width + x + 56) * 4
    padded.data.set(source.data.subarray(from, from + 4), to)
  }
}
check('sheet-grid.png with a border', analysePixels(padded).boxes, 4)

console.log(`6 detection checks on ${4} sample images`)
if (failures.length) {
  for (const failure of failures) console.error(failure)
  process.exit(1)
}
