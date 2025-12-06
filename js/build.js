import { copyFileSync } from 'node:fs'

copyFileSync('../build/dist/EngineConfiguration', './dist/EngineConfiguration')
copyFileSync('../build/dist/EnginePlayData', './dist/EnginePlayData')
copyFileSync('../build/dist/EngineWatchData', './dist/EngineWatchData')
copyFileSync('../build/dist/EnginePreviewData', './dist/EnginePreviewData')
copyFileSync('../build/dist/EngineTutorialData', './dist/EngineTutorialData')
copyFileSync('../build/dist/EngineRom', './dist/EngineRom')
copyFileSync('./res/thumbnail.png', './dist/thumbnail.png')
