import { readFile } from 'node:fs/promises'
import { join } from 'node:path'

export default defineEventHandler(async () => {
  const candidates = [
    join(process.cwd(), 'public/data/predictions.json'),
    join(process.cwd(), '../predictions.json'),
    join(process.cwd(), 'predictions.json')
  ]

  for (const path of candidates) {
    try {
      const raw = await readFile(path, 'utf-8')
      return JSON.parse(raw)
    } catch {
      // try next path
    }
  }

  throw createError({
    statusCode: 404,
    statusMessage: 'Predictions not found. Run `python predict.py` first.'
  })
})
