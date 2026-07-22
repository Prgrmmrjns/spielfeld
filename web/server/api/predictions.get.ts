// Bundled at build time so the Vercel serverless function does not depend on cwd/public FS.
import predictions from '../../public/data/predictions.json'

export default defineEventHandler(() => predictions)
