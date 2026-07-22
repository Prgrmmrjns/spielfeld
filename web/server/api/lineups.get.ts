import predictions from '../data/predictions.json'
import { buildLiveLineups } from '../utils/apiFootball'

export default defineEventHandler(async () => {
  return buildLiveLineups(predictions.predictions || [])
})
